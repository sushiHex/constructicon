### II.3 L0 — core contracts (complete at v0.1)

```python
# identity
RunId, NodeId, GitSha = NewType(...)
class ExecutionPath(BaseModel):
    """ONE hierarchical address per invocation (I13): string segments for
    component instances, int segments for loop iterations —
    issue-to-pr / claude-build-loop / repair[2] / builder.
    invocation_id = hash(run_id, segments) is THE identity used everywhere:
    envelopes, checkpoints, events, effect receipts, channel messages,
    cancellation, budget accounting, artifacts, API detail references.
    One invocation has one address, everywhere in the system."""
    segments: tuple[str | int, ...]

# envelopes & artifacts
class Envelope(BaseModel, Generic[T]):
    run_id: RunId; path: ExecutionPath; port: str
    created_at: AwareDatetime          # UTC; durations use monotonic clocks
    provenance: tuple[str, ...]
    payload: T
class ArtifactRef(BaseModel):
    commit: GitSha; paths: tuple[str, ...] = ()
    diff_against: GitSha | None = None
    media_type: str | None = None; size: int | None = None
class TextContext(BaseModel):          # literal text is typed, not a bare str
    text: str

# ports (I11): nominal typing; cardinality replaces schema-shape inference
class Port(BaseModel):
    name: str
    type_id: str                       # nominal identity, namespaced
    schema_hash: str
    schema_: JsonSchemaValue
    cardinality: Literal["one", "optional", "many"] = "one"   # "many" gathers
class GraphInputAddress(BaseModel):  port: str
class NodePortAddress(BaseModel):    node: NodeId; port: str
class GraphOutputAddress(BaseModel): port: str
PortAddress = GraphInputAddress | NodePortAddress | GraphOutputAddress

# graph IR — three constructs: reference, composition, bounded loop
class Ref(BaseModel):
    component: str                     # namespaced: "constructicon.std/panel"
    version: str | None = None         # None = STABLE at run start; "@<hash>" =
                                       # exact. v1 ships only these two;
                                       # "@candidate"/"@canary" are aliases that
                                       # arrive with M9 (I12: registration never
                                       # propagates — promotion does)
    bind: dict[str, str] = Field(default_factory=dict)   # capability aliases
    grants: Grants | None = None       # narrow only, never widen
class Loop(BaseModel):
    """Generic feedback loop. The IR knows how to feed outputs back to inputs and
    read a typed continuation decision — nothing else. Gate checking, triage, and
    repair are ordinary registered components inside the body (I10)."""
    body: "Ref | Graph"
    feedback: dict[str, str]           # next-iteration input -> previous output
    continue_from: str                 # body output: typed continuation decision
    max_iterations: PositiveInt
class GraphNode(BaseModel):
    id: NodeId
    body: "Ref | Graph | Loop"
class Connection(BaseModel):
    src: NodeId; dst: NodeId           # authored single connector (sugar level)
    map: dict[str, str] = Field(default_factory=dict)    # ambiguity override only
class Graph(BaseModel):
    schema_version: int
    name: str
    nodes: tuple[GraphNode, ...]; connections: tuple[Connection, ...]
    inputs: tuple[Port, ...] = (); outputs: tuple[Port, ...] = ()
    # boundary wiring (graph input → node input, node output → graph output)
    # is resolved to explicit PortAddress bindings at admission

# components & versions (I10)
class PythonRef(BaseModel):
    package: str; module: str; qualname: str
    contract_hash: str; source_digest: str
class ComponentDef(BaseModel):
    name: str                          # namespaced
    role: Literal["node", "component", "harness", "workflow"]   # semantic role
    body: PythonRef | Graph            # atomic | composite (the mechanical split)
    inputs: tuple[Port, ...]; outputs: tuple[Port, ...]
    content_hash: str                  # computed, read-only; version identity

# the sealed executable form (I13): compiled, immutable manifest of one run —
# executable + lockfile + deployment manifest in one object. After admission
# there is NO remaining magnetism, adjacency, scope search, or implicit
# boundary behavior: only explicit resolved edges.
class ResolvedPortBinding(BaseModel):
    destination: PortAddress
    sources: tuple[PortAddress, ...]   # >1 only for cardinality="many";
    # a gathering binding records its complete expected producer set
class ComponentResolution(BaseModel):
    scope: ExecutionPath; component: str
    requested_version: str | None; resolved_version: str
    contract_hash: str; implementation_digest: str | None
class CapabilityBinding(BaseModel):
    scope: ExecutionPath; binding: str; capability_id: str; revision: str
    effective_grants: Grants
    lifetime: Literal["invocation", "scope", "run"]   # build-loop worktree: "scope"
# At runtime each binding becomes a CapabilityLease (lease_id, scope, grants,
# lifetime) created after admission and finalized by the walker on every exit
# path. The manifest records descriptors and grants — never live objects or
# credentials; the runtime receives real capabilities by injection (I8).
class ExecutionManifest(BaseModel):
    schema_version: int
    source_graph: Graph; source_graph_hash: str
    resolved_components: tuple[ComponentResolution, ...]
    resolved_connections: tuple[ResolvedPortBinding, ...]
    capability_bindings: tuple[CapabilityBinding, ...]
    input_hash: str                    # the run's inputs
    world_hash: str                    # the transitive component resolution
    manifest_hash: str                 # identity of this sealed manifest
# The walker accepts ONLY an ExecutionManifest, never an authored Graph. One
# object answers: what ran, what connected, what was granted, what to resume,
# what to reproduce, what an attestation binds to, what to inspect.

# execution grants
class Posture(StrEnum): READ = "read"; WRITE = "write"
class Grants(BaseModel):
    posture: Posture = Posture.READ
    model: str | None = None           # None = backend default (model ≠ authority)
    effort: str | None = None
    allowed_tools: tuple[str, ...] | None = None   # None = inherit parent grant
    env_allowlist: tuple[str, ...] = ()
    network: Literal["inherit", "none"] = "inherit"
    timeout_s: PositiveInt | None = None

# executor outcomes (discriminated; replaces ok/partial booleans)
class ExecutorSuccess(BaseModel):
    status: Literal["success"]
    raw_reply: str
    output: JsonValue | None           # extracted structured output, pre-validation
    requested_model: str | None; served_model: str | None
    usage: Usage | None; rate_limit: RateLimitInfo | None; elapsed_s: float
class ExecutorPartial(BaseModel):
    status: Literal["partial"]
    raw_reply: str; output: JsonValue | None
    damage: TransportDamage            # counts + first error + bounded evidence
class ExecutorFailure(BaseModel):
    status: Literal["failure"]
    raw_reply: str | None; error: ExecutorError    # salvage fields per I4
ExecutorOutcome = ExecutorSuccess | ExecutorPartial | ExecutorFailure

# the effect chain (I2, I13): evidence → authority → outcome. ONE mechanism for
# every externally visible action — merge, open/update PR, mailbox send, artifact
# publish, stable-pointer move, approval, CI trigger.
#   GateCheck (what a check observed)
#     → Attestation (trusted deterministic policy authorizes THIS action on THIS
#       subject; journal-minted, referenced by id, never caller-supplied)
#       → EffectReceipt (what actually happened)
class GitProofSubject(BaseModel):
    kind: Literal["git"] = "git"
    repository: str; commit: GitSha; base: GitSha | None = None
    tested_tree: GitSha | None = None
class ComponentProofSubject(BaseModel):
    kind: Literal["component"] = "component"
    component: str; version: str; baseline_version: str
ProofSubject = GitProofSubject | ComponentProofSubject
class Attestation(BaseModel):
    attestation_id: str
    action: Literal["merge", "promote"]
    subject: ProofSubject
    checks: tuple[GateCheck, ...]
    gate_set_hash: str                 # exact gate/evaluator defs + config revisions
    evidence: tuple[ArtifactRef, ...]
    manifest_hash: str                 # the attesting run's sealed world (I12)
    created_by_run: RunId; workspace_id: str | None; created_at: AwareDatetime
class ApprovalRecord(BaseModel):       # the discretionary attestation
    approval_id: str; subject: ProofSubject; actor: AuthenticatedActor
    run_id: RunId; created_at: AwareDatetime

# release channels (I12): append-only; the channel pointer is derived from the
# latest valid record; rollback is another pointer move, nothing overwritten
class PromotionRecord(BaseModel):
    component: str
    channel: Literal["candidate", "canary", "stable"]
    from_version: str | None; to_version: str
    proof_id: str; actor: str; source_run: RunId; created_at: AwareDatetime

# learning metadata (I12) — optional on ComponentDef; a skill IS a ComponentDef
class LearningProfile(BaseModel):
    change_surfaces: frozenset[Literal["prompt", "policy", "graph", "code",
                                       "model_artifact"]]
    experience_policy: Ref; evaluator: Ref; promotion_policy: Ref
    evaluation_dataset: ArtifactRef | None = None
    impact_scope: Literal["component", "reverse_dependencies"] = "reverse_dependencies"
    requires_human_stable_approval: bool = True
class ComponentLineage(BaseModel):
    parent_version: str | None; created_by_run: RunId
    experience_set: ArtifactRef | None; proposer_resolution_hash: str | None

# effects (at-least-once, bounded by idempotency)
class EffectRequest(BaseModel):
    path: ExecutionPath; kind: str; subject: JsonValue
    idempotency_key: str               # hash(manifest_hash, path, kind, subject)
    attestation_id: str | None = None  # required for authority-bearing kinds
class EffectReceipt(BaseModel):
    request_hash: str
    status: Literal["committed", "rejected", "unknown"]
    external_reference: str | None; observed_state: JsonValue | None
# journaled prepared→receipt around execution; recovery re-observes "unknown"
# before ever re-executing — resume recovers the first PR, it never opens a second

# journal
class JournalEvent(BaseModel):
    schema_version: int
    run_id: RunId; seq: int            # per-run monotonic, allocated in SQLite
    path: ExecutionPath | None
    ...                                # discriminated union; payload size-capped,
                                       # large outputs by reference; redaction
                                       # rules for prompts/replies/secrets/env
class Checkpoint(BaseModel):
    run_id: RunId; path: ExecutionPath
    input_hash: str
    outputs: dict[str, Envelope[Any]]  # by-reference beyond size cap
    worktree: GitSha | None
```

Errors (one taxonomy): `ContractViolation` · `ExecutorFailure` · `TransportDamage`
· `BudgetExhausted` · `Cancelled` · `JournalDamaged`. A red gate is data, not an
error.

**Port resolution rules (I11), fixed for v1:** (1) exact `type_id` + schema
revision match; (2) an explicitly registered adapter component; (3) `list[X]`
gathers all upstream ports whose type_id is exactly `X`; (4) a small documented
optional/union rule set; (5) no general JSON-Schema subsumption. Exact-name
matches must be unique; nested component internals are invisible unless exported;
graph inputs participate in scope; defaults are explicit; Ref resolution precedes
binding; a second candidate fails validation rather than rebinding.
