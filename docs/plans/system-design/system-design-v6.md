# Constructicon — System Design (v6)

## Context

Constructicon is a system — an OS for agentic software-engineering pipelines. It must
build both simple and advanced system graphs, expose an SDK (authoring) and an API
(control), be easy to develop in and contribute to, be elegant and structured above
all, be highly modular in code and in graph, stand on complete high-level structure
from the start, layer its complexity, and carry no duplicated structure anywhere.
**Agents are the first-class user; humans are secondary** — observational, advisory,
and high-level approval only. **Layering means building from higher-level components
first**: complexity is always constructed by composing simpler components; every
component is defined once and referenced by name, so an update to a component is
picked up by every downstream dependent and reference automatically.
Inputs: the brainstorm document, seven argued positions, and two vendoring sources —
sushiHex/hardline-mcp (subscription-CLI adapters, durable SQLite mailbox; at
/home/user/sushihex/hardline-mcp) and disler/fusion-harness (multi-model panel /
debate / fusion / validated-delegation topologies; at /home/user/disler/fusion-harness).

## Part I — Settled decisions

1. **One graph IR is the single source of truth** (supersedes the earlier
   "workflows are arbitrary async code" stance, deliberately). The SDK's typed
   combinators and decorators *compile to* the IR; advanced users construct the IR
   directly; LLM architects *propose* IR that deterministic validation admits.
   Simple and advanced graphs are one structure with two authoring surfaces — no
   duplicated workflow model, no separate "Plan" type, and graph serialization is
   native (the IR's JSON form), so there is no DSL question left to defer.
2. **Executor seam** (user's words): "all models whether subscription or API fit the
   same data model schema; interchangeable as nodes/plugs." Task-shaped contract;
   no completion-level provider layer, ever.
3. **Workspace**: git worktree per write grant; proof-carrying gate-locked merge;
   discard-by-default rollback.
4. **hardline-mcp**: vendor the patterns (async-native, credited), no pip dep.
5. **Channels v1**: typed InProcess + Mailbox transports; panel pattern in v1;
   debate/fusion-ACK as later pattern additions.
6. **Journal**: LangGraph's checkpoint *model* in an owned plain-JSON schema —
   events as per-run JSONL, checkpoints/jobs in SQLite WAL, OTel GenAI exporter
   optional. Resume = re-walk the graph skipping checkpointed nodes (the graph IR
   makes memoized-replay of code unnecessary — simpler than v3).
7. **First workflows**: issue→PR with gates (write path); multi-model review panel
   (read path).
8. **Never**: LLM watchdogs, completion-level provider interface, CloudEvents
   internally, custom scheduler beyond the graph walker. Python ≥ 3.11.
9. **Agents are the first-class user** (invariant I9). Consequences settled with it:
   the MCP server is the v1 control surface, not a deferral; architect-proposed
   graphs are a primary authoring path; humans enter only as observer (event
   stream), advisor (channel endpoint), or approver (ApprovalRecord parking proof) —
   no parallel human machinery; every API response is bounded and pageable with
   detail by reference; contributor docs (AGENTS.md/CLAUDE.md) and the single
   `verify` command are written for agent contributors first.
10. **Composition with reference semantics** (invariant I10). The component ladder —
    functions → atomic nodes → components (named compositions) → harnesses
    (components with bound policies/grants/capabilities) → workflows — builds each
    tier only from tiers below, and authoring reaches for existing higher-level
    components before writing new primitives. Definitions live once in the registry
    and are referenced by name; references resolve at run start (late binding), so
    an updated component reaches every graph that references it on its next run.
    **Reproducible means everything is versioned at the component level** (user's
    words): every registered version is immutable, retained, and addressable;
    each run journals its exact resolution and can be reproduced from it. The IR
    shrinks to a minimal algebra (ref | graph | loop) and former specials like
    `panel` become ordinary registered components.
11. **Single-connector wiring with magnetic ports** (invariant I11, user's words:
    "modular nodal connections should only need a single connector; the granular
    connections should be as automatic as possible, magnetically attracted in and
    outs; nodes support zero or multiple inputs or outputs depending on their
    function"). Nodes declare typed ports (zero or more in, zero or more out);
    connecting two nodes is one act; per-port binding is resolved automatically by
    deterministic rules at validation time; ambiguity is an itemized error with a
    granular override, never a guess.

## Part II — The system

### II.1 The eleven invariants (review law — a change violating one is wrong even if it works)

- **I1 — Authority is physical.** Effects (merge, rollback, run transitions) belong
  to deterministic code operating on git and the journal. LLMs propose — work *and*
  structure; code validates, executes, disposes.
- **I2 — Effects carry proof.** Merging requires a `GateResult` bound to the exact
  SHA merged; `approve()` re-verifies. Nothing self-certifies.
- **I3 — No ambient authority.** Capabilities (workspace, executors, channels,
  budget) reach a node only through its declared bindings. A proposed graph can only
  wire *registered* nodes with *granted* capabilities — an architect wires topology;
  it can never inject code or widen a grant.
- **I4 — Truthful telemetry.** Unemitted fields are None, never inferred; damaged
  streams demote to `partial`, never report ok; timeouts salvage partial output.
- **I5 — Control plane typed, data plane in git.** Envelopes cross boundaries; code
  crosses as commits; `ArtifactRef` bridges. Channels carry typed envelopes only.
- **I6 — Two implementations or no abstraction.** Inventory in II.7.
- **I7 — The fake path is the tested path.** Full lifecycle in CI with zero
  credentials; recorded transcripts test drivers; live runs are an opt-in lane.
- **I8 — One structure per concept, layered strictly downward.** Every concept has
  exactly one defining type in exactly one layer; higher layers add surface, never
  parallel structure. Imports flow downward only (mechanically enforced in CI).
- **I9 — Agents are the first-class user.** Every surface is designed for machine
  callers: responses are structured, bounded, and pageable, with full detail
  available by reference, never dumped by default (a caller's context window is a
  scarce resource — hardline's inbox clamp generalized to every list/read API);
  errors are self-describing and name the fix; the system is discoverable by
  introspection (`system.describe()`, published JSON schemas) so an agent can learn
  to wire it without reading source. Humans participate through the same contracts —
  observer on the event stream, advisor as a node, approver as a parking proof — and
  every human rendering is derived from the machine form.
- **I10 — Complexity composes; definitions propagate.** Every construct above an
  atomic node is a composition of simpler components, never a monolith; new work
  builds from the highest existing tier that fits before dropping to primitives.
  A component is defined once, registered by name, and referenced — never copied.
  **Everything is versioned at the component level**: registering a changed
  definition creates a new immutable version (content hash = version identity);
  prior versions are retained and addressable, never overwritten. References
  late-bind to latest at run start — so an update reaches every downstream
  dependent and reference on its next run — or pin an explicit version where
  stability is wanted; each run journals its full resolution (every component at
  its exact version), and because versions are immutable and retained, that
  resolution is *re-executable*: `runs.reproduce(run_id)` starts a new run under a
  past run's exact component world. `system.rdeps(name)` answers "what does
  changing this touch" before it is changed.
- **I11 — One connector; magnetic, deterministic binding.** Nodes expose typed
  ports — zero or multiple inputs and outputs, per their function. Wiring two
  nodes is a single connector; the granular port-to-port bindings resolve
  automatically by deterministic rules (exact name + compatible schema, else
  unique compatible schema, over the upstream dataflow scope; a `list[X]` input
  gathers multiple `X` outputs as declarative fan-in). Zero candidates or more
  than one is a validation error naming the port and the candidates, repairable
  with a per-port override — automatic never means guessed. The fully bound graph
  is journaled and inspectable, so what attracted to what is a fact on record,
  not an inference.

### II.2 Layered architecture

```
L4  api        Constructicon system object · run control · event streams ·
               MCP server (v1 front door, I9) · CLI skin · (HTTP later)
L3  sdk        authoring surface: @task, combinators (seq/fanout/loop/
               worktree_scope), component/harness registration — pure sugar
               compiling to L2; patterns (panel, review, build-loop) are
               registered components, not language specials (I10)
L2  runtime    the graph IR (single source of truth) · component registry &
               resolution · validator · walker/scheduler · resume · budget
L1  substrate  workspace (git) · executors · gates · channels · journal —
               each a service over the OS, depending only on L0
L0  core       contracts: every basic type in the system, defined once
```

The kernel is L0–L2; userland is L3–L4. Two orthogonal ladders, one word "layer"
(the distinction is deliberate): the **code layers** above import strictly downward
(I8); the **component ladder** — functions → atomic nodes → components →
harnesses → workflows — composes strictly upward from simpler pieces (I10).
Authoring happens as high on the component ladder as possible; dropping a tier is
the exception that needs a reason. A workflow author touches L3 only; a contributor
adding an executor touches L1 against L0 types; only kernel work touches L2. Import
direction is law: `core ← substrate ← runtime ← sdk ← api`, enforced with an
import-linter contract in CI.

### II.3 L0 — core: the complete type system, present from the start

All basic types ship in v0.1, defined once, imported everywhere (I8). Sketches:

```python
# identity & envelopes
RunId, NodeId, GitSha = NewType(...)
class Envelope(BaseModel, Generic[T]):
    run_id: RunId; node: NodeId; port: str; seq: int
    created_at: AwareDatetime; provenance: tuple[NodeId, ...]
    payload: T

class ArtifactRef(BaseModel):
    commit: GitSha; paths: tuple[str, ...] = (); diff_against: GitSha | None = None

# execution
class Posture(StrEnum): READ = "read"; WRITE = "write"
class Grants(BaseModel):
    posture: Posture = Posture.READ
    model: str | None = None          # None = backend default, never second-guessed
    effort: str | None = None         # validated per backend pre-spawn, no downgrade
    allowed_tools: tuple[str, ...] | None = None
    timeout_s: PositiveInt | None = None
class TaskSpec(BaseModel):
    instruction: str
    context: tuple[ArtifactRef | str, ...] = ()
    response_schema: JsonSchemaValue | None = None
class ExecutorReport(BaseModel):
    ok: bool; reply: str; partial: bool = False           # I4
    requested_model: str | None; served_model: str | None # I4: None ≠ guessed
    usage: Usage | None; rate_limit: RateLimitInfo | None
    error: ExecutorError | None; elapsed_s: float

# verification (the proof type — one for all effects, I2)
class GateCheck(BaseModel): name: str; ok: bool; detail: str; elapsed_s: float
class GateResult(BaseModel):
    head: GitSha; checks: tuple[GateCheck, ...]
    @property
    def ok(self) -> bool: ...

# graph IR — a minimal algebra of THREE constructs (I10): reference, composition,
# bounded loop. Everything richer (panel, review, build-loop, whole workflows) is a
# registered COMPONENT built from these — never a new IR construct.
class Ref(BaseModel):
    component: str                     # name in the Registry — never code (I3)
    version: str | None = None         # None = latest at run start (late binding);
                                       # resolution is pinned per run (I10)
    bind: dict[str, str] = {}          # capability bindings by granted alias
    grants: Grants | None = None       # narrow (never widen) the caller's grants
class Loop(BaseModel):
    body: "Ref | Graph"
    until_gates: tuple[str, ...]
    policy: LoopPolicy                 # max_attempts=5, triage_after=3, gate_repair
class GraphNode(BaseModel):
    id: NodeId
    body: "Ref | Graph | Loop"         # the whole algebra; Graph nests (modularity)
# ports & connections (I11): nodes expose ZERO OR MORE typed ports each way —
# sources have no inputs, sinks no outputs. A Connection is the single connector
# between two nodes; per-port bindings are RESOLVED, not authored: exact
# name + compatible schema, else unique compatible schema, over the upstream
# dataflow scope; a list[X] input gathers every upstream X (declarative fan-in).
# `map` exists only to break ambiguity the resolver refuses to guess about.
class Port(BaseModel):
    name: str; schema_: JsonSchemaValue
class Connection(BaseModel):
    src: NodeId; dst: NodeId           # the single connector
    map: dict[str, str] = {}           # dst_port -> "node.port", ambiguity only
class Graph(BaseModel):
    name: str
    nodes: tuple[GraphNode, ...]; connections: tuple[Connection, ...]
    inputs: tuple[Port, ...] = (); outputs: tuple[Port, ...] = ()

# a Component is a named, versioned definition in the Registry: either an atomic
# node (Python implementation) or a Graph fragment (composition). One definition,
# referenced everywhere. Every version is IMMUTABLE and retained (I10):
# registering a changed body creates a new version; nothing is overwritten.
class ComponentDef(BaseModel):
    name: str; tier: Literal["node", "component", "harness", "workflow"]
    body: PythonRef | Graph            # atomic (code) or composite (IR)
    inputs: tuple[Port, ...]; outputs: tuple[Port, ...]   # zero or more each (I11)
    content_hash: str                  # derived; the version identity
    # composite bodies (IR) are fully reproducible from the store alone; a
    # code body's identity covers its declared contract + source hash, and the
    # run journal additionally records package version + host repo SHA — the
    # honest boundary of what a registry can guarantee for live code (I4).

# journal (one event schema: JSONL rows, run.events() stream, and OTel export
# all derive from these — I8)
class JournalEvent(BaseModel): ...     # discriminated union: NodeStarted/
                                       # NodeCompleted/GateRan/MergeApproved/
                                       # ExecutorSpawned/ChannelSent/RunParked/...
class Checkpoint(BaseModel):
    run_id: RunId; node: NodeId; seq: int
    input_hash: str
    outputs: dict[str, Envelope[Any]]  # one envelope per output port
    worktree: GitSha | None
```

Errors (one taxonomy, L0): `ContractViolation` (boundary validation failed — a bug,
fail fast) · `ExecutorFailure` (spawn/timeout/exit — carries salvage per I4) ·
`TransportDamage` (partial parse — demoted result) · `BudgetExhausted` (carries
attempt history) · `Cancelled` (cooperative; kill-tree + cross-process via jobs
table). A red gate is *not* an error — it is data the loop consumes.

### II.4 L1 — substrate: services, each behind one protocol

- **workspace/** — `Workspace.worktree()` async CM yielding `Worktree` (`head()`,
  `diff()`, `approve(proof) -> GitSha`). Approve verifies proof-to-SHA binding (I2),
  serializes merges on a per-repo lock. Exit without approve discards — rollback is
  the default, keeping changes takes the extra step.
- **executors/** — `Executor.execute(task, *, workspace, grants) -> ExecutorReport`.
  Implementations: `FakeExecutor` (scripted; the CI backbone), `ClaudeCodeExecutor`
  (`claude -p` stream-json; READ = denied write tools + stripped settings, WRITE =
  worktree + bypassPermissions), `CodexExecutor` (`codex exec --json`, sandbox
  pinned explicitly, never inherited), `PiExecutor` (API-billed multi-model,
  `pi --mode json -p`). All vendored from hardline/fusion adapter logic,
  async-native, with their measured lessons kept as tests (argv capture, damaged-
  stream demotion, partial-output salvage).
- **gates/** — `Gate.check(wt) -> GateCheck`; `run_gates(wt, gates) -> GateResult`
  snapshots HEAD before/after (moved HEAD voids the proof). Ships `PytestGate`,
  `RuffGate`, plus gate-first helpers (validator authors the gate; a baseline run
  must prove it red before building — fusion's discipline).
- **channels/** — `Channel[M].send/receive` over `Envelope[M]`. `InProcessChannel`
  (asyncio) and `MailboxChannel` (vendored hardline SQLite WAL: send/inbox/ack,
  lanes, bounded batches, history-as-recovery).
- **journal/** — per-run dir (events.jsonl + artifacts + summary.json) and one
  SQLite WAL DB (`runs`, `checkpoints`, `jobs` — jobs carries owner/child pid +
  identity key for cross-process cancel and lost-detection). Optional OTel GenAI
  span exporter reads the same JournalEvent stream (I8).

### II.5 L2 — runtime: the graph is the machine

- **Registry** — the single home of every `ComponentDef` (atomic nodes, composites,
  harnesses, workflows) and every capability object (executors, gates, channels).
  Definitions are code or IR; topology is data; the boundary is the registry (I3).
  The store is **versioned and immutable** (I10): every registration of a changed
  body appends a new version (content hash = identity) to the components table;
  prior versions stay addressable forever (`name` = latest, `name@<hash>` = exact).
  **Resolution** happens once per run start: every `Ref` resolves to an exact
  version, the full resolution is journaled, and the run executes against it — so
  an updated component propagates to every dependent's *next* run while in-flight
  and resumed runs keep their world. Because versions are retained, a journaled
  resolution is re-executable: `runs.reproduce(run_id)` replays a past run's exact
  component world as a new run. `registry.rdeps(name)` returns the
  reverse-dependency closure — what a change touches, answerable before changing it.
  In-package registration now; entry points when third-party packages exist
  (deferred, I6).
- **Validator** — admits a `Graph` only if: every `Ref` resolves; **port
  resolution succeeds** (I11: for each unbound input port, candidates are found by
  exact name + compatible schema, else by unique compatible schema, over the
  upstream dataflow scope; `list[X]` inputs gather all upstream `X` producers;
  zero or multiple candidates is an itemized, per-port error with the `map`
  override named in the message); no cycles outside `Loop`; every WRITE grant
  binds a workspace; capability bindings are within what the caller granted. The
  output is the **fully bound graph** — every input port carrying its resolved
  source address — which is what the walker executes and the journal records:
  magnetic binding is deterministic and on the record, never a runtime guess.
  This is the *one* validation path — SDK-built, hand-built, and
  architect-proposed graphs all pass through it (I8). Cycle detection and
  assignee/mode checks generalize fusion-harness's `validateCollaborationPlan`.
- **Walker** — dependency-driven execution over asyncio: a node fires the moment
  every input port has its envelope (a source node, having zero inputs, is ready
  at start; a gathering `list[X]` port waits for all its producers and verifies
  the expected count — the silent-node-failure defense); independent nodes
  overlap; TaskGroup wrapped to capture per-task results instead of first-failure
  sibling cancellation. The walker understands exactly the three IR constructs —
  resolve a `Ref`, descend a `Graph`, iterate a `Loop` under its policy with
  failure feedback verbatim. No other scheduler exists.
- **Resume** — a run is `(graph, inputs, checkpoints)`. Resume re-walks the graph;
  nodes whose `(node, seq, input_hash)` checkpoint exists return their recorded
  envelope; the first miss resumes live. Forking a run from a checkpoint prefix and
  time-travel fall out for free. (Simpler than v3's memoized code replay — the IR
  removes the need for any determinism constraint on user code, because there is no
  user code between nodes.)
- **Budget** — accumulates every report's usage/rate-limit (overage flags included)
  per run and per executor; v1 records and exposes, `LoopPolicy` and timeouts are
  the only enforcement; window-aware scheduling plugs in later without
  re-instrumentation.
- **Run lifecycle** — `PENDING → RUNNING → {SUCCEEDED | FAILED | CANCELLED |
  PARKED}`; PARKED = policy exhausted, escalated to a human with resume state
  intact. Node records: `queued → running → {completed | failed | lost}` — `lost`
  is reported, never silently vanished (hardline's rule).

### II.6 L3 sdk + L4 api — the two surfaces

**SDK (authoring).** Typed sugar that *builds and registers* components — mypy
checks composition at the combinator signatures; the validator re-checks the same
facts on the built IR. Authoring follows the component ladder (I10): reach for the
highest registered tier that fits; every `flow`/`harness`/`component` call registers
a named definition that other graphs reference — never copy.

Ports come from signatures (I11): each `@task` parameter is an input port (name +
schema from its annotation), the return annotation is the output port; multi-output
nodes declare named outputs; a no-parameter function is a source, a `-> None`
function is a sink. Adjacency in `flow(...)` (or `a >> b`) is the single connector;
the resolver does the granular binding over the flow's upstream scope — so in
`flow("issue-to-pr", triage, "claude-build-loop", open_pr)`, an
`open_pr(merged: MergedChange, brief: BuildBrief)` signature magnetically pulls
`merged` from the build harness and `brief` from `triage` two steps upstream, with
nothing authored but the chain itself. A per-port `bind()` override exists only for
the ambiguity cases the resolver refuses to guess about.

```python
from constructicon.sdk import task, component, harness, flow, agent, loop, worktree_scope
from constructicon.std import panel     # stdlib COMPONENT, not a language special

@task                                   # tier 1: atomic node; name = function name
async def triage(issue: Issue) -> BuildBrief: ...

# tier 3: a harness — a composition with policies/grants/capabilities bound.
# Registered once; every workflow that Refs it picks up changes on its next run.
claude_build = harness(
    "claude-build-loop",
    worktree_scope(
        loop(
            agent("claude", grants=WRITE, render=build_task),
            until=("pytest", "ruff"),
            policy=LoopPolicy(max_attempts=5, triage_after=3),
        )
    ),
)

# tier 4: workflows compose registered components BY NAME (Refs in the IR)
issue_to_pr = flow("issue-to-pr", triage, "claude-build-loop", open_pr)

frontier_review = component(          # tier 2: a reusable composition
    "frontier-review",
    panel(
        ("claude", ADVISOR), ("codex", ADVISOR), ("pi:google/gemini-3.7", ADVISOR),
        render=review_task, schema=ReviewOpinion, quorum=2,
    ),
)
review_change = flow(
    "review-change",
    "frontier-review",                   # Ref — updating frontier-review updates this
    task(dedupe_findings),               # lift a plain function inline
    synthesize,
)
```

Advanced graphs use the same IR directly — hand-constructed `Graph(...)`, loaded
from its serialized JSON form, or **proposed by an architect node and admitted by
the validator** (the fusion collaborate pattern, now first-class):

```python
proposed = await propose_plan(architect, brief)      # LLM output: JSON
graph = Graph.model_validate(proposed)               # same IR
run = await system.runs.start(graph, inputs)         # same validator, same walker
```

**Graph authoring is agent-first.** The architect-proposed path is a *primary*
authoring surface, not the advanced case: the published Graph JSON schema plus
`system.describe()` (registry contents, node signatures, available capabilities,
grant vocabulary) is the complete contract an agent needs to author a valid graph
from nothing. The SDK combinators are the same contract for agents that author in
Python. Validation errors are itemized per fault and name the fix (fusion-harness's
validator style), because the consumer of a rejection is an agent that will repair
and resubmit.

**Humans are plugs into the agent-shaped system** (I9), through three mechanisms and
no others — no parallel human machinery exists:
- *Observer*: the JournalEvent stream and derived renderings (summary views over the
  same events; no separate human data model).
- *Advisor*: a human is an endpoint on a Channel — a task envelope goes out (via
  MailboxChannel; a human-driven session answers on its own rhythm), a typed opinion
  envelope comes back, indistinguishable in contract from any other advisor node.
- *Approver*: where a graph opts in, an `approval` node parks the run (PARKED, resume
  state intact) and resumes on an `ApprovalRecord` — the discretionary counterpart of
  `GateResult`, likewise bound to the exact SHA it approves (I2). Approval is opt-in
  per graph; the default workflow runs fully autonomous.

**API (control).** One system object; every surface is a thin skin over it, adding
no new concepts (I8). **The MCP server is the v1 front door** — agents are the
first-class operator, and this user's agents already operate infrastructure over
MCP — with tools mirroring the API one-to-one (`runs_start`, `runs_status`,
`runs_events` paged, `runs_cancel`, `runs_resume`, `runs_reproduce`,
`runs_approve`, `graphs_validate`, `graphs_describe`, `system_describe`,
`registry_rdeps`), every response bounded with by-reference expansion into the
journal (I9). The CLI is a human convenience
skin over the same object; HTTP service later:

```python
system = Constructicon(
    workspace=Workspace("/repo"),
    executors=[claude, codex, pi, fake],
    gates=[PytestGate(), RuffGate()],
    journal=Journal(root=...),
)
run = await system.runs.start(issue_to_pr, issue)
async for event in system.runs.events(run.id): ...   # JournalEvent stream
await system.runs.cancel(run.id)                     # cross-process capable
resumed = await system.runs.resume(run.id)
system.graphs.validate(graph); system.graphs.describe(graph)
```

The elegance test stands: if a feature makes `issue_to_pr` or `review_change`
uglier, the feature is wrong.

### II.7 Repository & contribution structure

```
constructicon/
├── src/constructicon/
│   ├── core/         L0 — one module per concept group; no intra-layer deps
│   ├── substrate/    L1 — workspace/ executors/ gates/ channels/ journal/
│   ├── runtime/      L2 — registry, validator, walker, resume, budget
│   ├── sdk/          L3 — task, flow, combinators, patterns
│   └── api/          L4 — system object, CLI
├── tests/            mirrors src layer-for-layer + e2e/ (fake lifecycle, resume)
├── examples/         the two workflows as living, executed documentation
├── docs/             ARCHITECTURE.md (Part II of this plan), INVARIANTS.md,
│                     CONTRIBUTING.md (how to add an executor/gate/channel in
│                     one page each — the extension protocols make this mechanical)
├── AGENTS.md         the contributor guide for the first-class contributor (I9):
│   + CLAUDE.md       layer map, invariants, extension recipes, the one
│                     verification command, and the authoring rule (I10): check
│                     `system.describe()` for an existing component before writing
│                     a new one; compose before you drop a tier
└── pyproject.toml    uv-managed; ruff + mypy --strict on src; import-linter
                      enforcing the layer contract; pytest
```

Contributing is layered like the code: adding a gate or executor is an L1 exercise
against L0 protocols with a one-page guide and a fake to copy; graph combinators are
L3 PRs; kernel (L2) changes require an invariant review. The expected contributor is
an agent (I9): one command (`uv run verify`) runs lint, types, layer contract, and
the full fake lifecycle, so an agent self-verifies before pushing; CI repeats the
same command, so green-local means green-CI with no credentials anywhere (I7).

**Dependency budget (enforced, not aspirational).** The kernel (L0–L2) has exactly
one third-party runtime dependency: **Pydantic** — it is the contract system, and
the agent-facing surface (derived JSON Schemas in `system_describe`, the published
Graph schema, itemized validation errors agents repair against) comes from it for
free; dataclasses + hand validation would rebuild that surface at higher cost. The
import-linter contract enforces the budget mechanically: kernel layers import
stdlib + pydantic only, so a PR adding a kernel dependency fails CI. Things that
look like dependencies but are not:
- **SQLite is stdlib** (`sqlite3`) — zero packaging cost. Used only where files
  would force re-engineering what it already solves: the mailbox channel
  (multi-process concurrent writers; atomic inbox claims — the measured
  double-delivery race), cross-process job cancel / lost detection, and registry
  version + rdeps queries. Events and artifacts stay plain files (single-writer,
  append-only, greppable). One WAL database = one concurrency story.
- **git** — subprocess-invoked environment requirement (no GitPython/pygit2); a
  host without git has no work for this system.
- **Agent CLIs** (claude, codex, pi) — per-executor environment requirements; an
  absent CLI makes that executor report unavailable (per-agent skip), and the
  Fake executor keeps the whole system runnable with none installed.
- Optional extras, never imported by the kernel: `constructicon[mcp]` (L4 server),
  `constructicon[otel]` (journal exporter).
- Cut outright: YAML (graph JSON is stdlib), CloudEvents, any HTTP client in core.
  Dev tooling (uv, ruff, mypy, pytest, import-linter) never ships.

| Extension point | Shipped implementations (I6) |
|---|---|
| Executor | Fake + ClaudeCode at v0.1; Codex, Pi as workflows exercise them |
| Gate | Pytest + Ruff |
| Channel transport | InProcess + Mailbox |
| Journal sink | JSONL + SQLite (OTel exporter optional third) |
| Graph authoring surface | SDK combinators + direct/proposed IR |
| Workflow | issue→PR + review panel |

### II.8 Build order

1. **L0 core** — the complete type system above, with schema tests (every model
   round-trips JSON; graph JSON schema published).
2. **L2 registry + validator** (needs only L0) — ComponentDef store, content
   hashing, Ref resolution with per-run pinning, `rdeps`; admit/reject graphs;
   property tests with generated graphs; fusion's plan cases ported as fixtures.
3. **L1 workspace + journal** — worktree CM, proof-carrying approve, events +
   checkpoints; scratch-repo fixtures.
4. **L1 executors** — Fake, then ClaudeCode (vendored, async): recorded-transcript
   + argv tests.
5. **L2 walker + resume + L1 gates** — the fake E2E lifecycle test goes green:
   graph in → build → gate-fail → loop → gate-pass → proof merge; kill-and-resume.
6. **L3 sdk + L4 api** — combinators compile to IR; system object; **MCP server**
   (the agent front door) + CLI skin; `examples/` become executable docs.
7. **L1 channels + L3 panel** — two-process mailbox test; review workflow green;
   human-as-advisor and approval/PARKED round-trips exercised over the same
   channels.
8. **Codex + Pi executors; architect-proposed graph path** end-to-end (an agent
   authors a graph from `system_describe` + the published schema, submits it over
   MCP, and drives it to a proof-carrying merge).

## Deferred, with named triggers

- HTTP service skin over L4 → first non-MCP external consumer (MCP itself is v1).
- Entry-point registration → first out-of-tree extension package.
- Debate rounds + fusion-ACK patterns → first workflow needing adversarial rounds.
- Budget *enforcement* (window-aware scheduling) → first starved subscription window.
- Local/open-weight executors beyond Pi → when local models arrive.
- Distributed/durable backend (wrap Temporal, don't rebuild) → outgrowing one machine.
