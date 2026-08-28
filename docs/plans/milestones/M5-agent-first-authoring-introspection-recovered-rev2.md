# M5 — agent-first authoring & introspection

> **Recovery note:** This is a high-confidence reconstruction of the revised M5 plan that disappeared from the ChatGPT conversation. Its milestone, architectural constraints, acceptance path, and red-team corrections are recoverable from the surviving user prompt and frozen records. Exact lost prose is not recoverable. The declarative component capability-requirement contract is an implementation inference required to make `system.describe()` a complete authoring surface against the current M4 codebase.

## Context

M1–M4 are merged. M5 is the first milestone whose product is primarily consumed by agents rather than by the walker or substrate:

> **SDK combinators; `system.describe()`; architect-proposed graph admission; agent-repairable errors end-to-end.**

The frozen acceptance line is:

> an agent using only schemas, describe, and errors authors and repairs a valid read-only graph.

M4 completed the three-construct runtime. `Ref`, `Graph`, and `Loop` now admit into one sealed `ExecutionManifest`; loop structure, feedback, continuation, exports, and member order are compiled before execution. M5 adds no execution semantics and no fourth construct. It exposes the machine that already exists through two equivalent authoring surfaces:

```text
Python SDK sugar ─┐
                  ├─> the same Graph ─> the same validator ─> ExecutionManifest
Graph JSON ───────┘
```

The present gaps are deliberately narrow:

- `constructicon.sdk` is still a stub;
- `Constructicon.describe()` exposes only component version names and capability kind/revision;
- `AdmissionError.faults` is a list of strings rather than a stable machine contract;
- raw architect JSON has no one-call parse → reject/accept surface;
- atomic component definitions do not yet declare the capability aliases their implementations require, so introspection cannot fully teach an architect how to bind them.

**Acceptance criterion:** a scripted architect receives only the published Graph schema and a bounded `SystemDescription`; proposes invalid Graph JSON; receives typed, itemized faults naming the repair; changes only the JSON; resubmits through the same admission path; receives an accepted `ExecutionManifest`; and executes a valid READ graph. The equivalent SDK-authored graph and hand-authored graph are structurally equal and produce the same `source_graph_hash`, `world_hash`, and `manifest_hash` under the same snapshot and inputs.

Pinned assertions:

```text
one Graph IR
one validator
one RegistrySnapshot per admission
one catalog as capability truth
one typed fault model
one schema publication path
SDK == direct JSON == architect proposal after compilation
no SDK object reaches the walker
no new metadata store
no automatic repair in the kernel
```

## 1. Core contracts: describe, admission, and capability requirements

### 1.1 Graph IR and manifest remain unchanged

M5 makes **no change** to `core/graph.py` and adds no execution field to `ExecutionManifest`.

The SDK may retain temporary Python authoring handles, but every combinator immediately builds canonical `Ref | Graph | Loop` values. No SDK AST is serializable, journaled, admitted, or interpreted by runtime code.

### 1.2 Declarative capability requirements on component definitions

A component contract is not complete if an architect can see its ports but cannot know which capability aliases must be bound. Add one additive contract:

```python
class CapabilityRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    alias: str
    kind: str
    optional: bool = False


class ComponentDef(BaseModel):
    ...
    capability_requirements: tuple[CapabilityRequirement, ...] = ()
```

Rules:

- the requirement names an alias and a capability **kind**, never a live object or environment-specific credential;
- required aliases must appear in `Ref.bind`;
- optional aliases may be omitted;
- a bound capability descriptor must have the declared kind;
- undeclared extra bindings are rejected: a component receives no authority it did not declare;
- duplicate aliases are rejected;
- the requirement tuple participates in component identity only when non-empty, preserving hashes of historical definitions whose contract predates this field;
- old definitions with no requirements continue to load, but `system.describe()` marks capability completeness truthfully rather than inferring hidden requirements from code.

All current M3/M4 fixture components that use `ctx.capability(...)` are updated to declare their aliases. No registry side table and no SQLite migration are introduced.

### 1.3 Typed admission faults

Replace string-only faults with one stable model while preserving readable exception text:

```python
class AdmissionFault(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    message: str
    path: tuple[str | int, ...] = ()       # JSON/Pydantic location
    scope: ScopePath | None = None         # resolved semantic location
    repair: str                            # imperative, repair-naming guidance
    details: dict[str, JsonValue] = Field(default_factory=dict)


class AdmissionError(ConstructiconError):
    faults: tuple[AdmissionFault, ...]

    def __str__(self) -> str:
        return "; ".join(fault.message for fault in self.faults)
```

Stable v1 fault families:

```text
graph.schema.*
graph.node.duplicate
graph.reference.unknown
graph.reference.unpromoted
graph.port.missing_source
graph.port.ambiguous
graph.port.contract_mismatch
graph.capability.missing_binding
graph.capability.undeclared_binding
graph.capability.unknown
graph.capability.kind_mismatch
graph.grant.widening
graph.loop.invalid
graph.cycle
graph.contract.invalid
```

Examples:

```json
{
  "code": "graph.port.ambiguous",
  "path": ["nodes", 3, "body"],
  "scope": {"segments": ["review", "summarize"]},
  "message": "input 'brief' has two upstream sources with the required nominal contract",
  "repair": "add a Connection.map override selecting one source",
  "details": {
    "destination_port": "brief",
    "candidates": ["triage_a.brief", "triage_b.brief"],
    "map_example": {"brief": "triage_a.brief"}
  }
}
```

Pydantic `Graph.model_validate*` errors are translated into the same model. Raw invalid input values are not echoed by default; paths, error types, expected shape, and bounded context are enough for repair.

### 1.4 Admission result union

Expected authoring rejection is data, not an exception at the agent-facing boundary:

```python
class AdmissionAccepted(BaseModel):
    status: Literal["accepted"] = "accepted"
    graph: Graph
    manifest: ExecutionManifest


class AdmissionRejected(BaseModel):
    status: Literal["rejected"] = "rejected"
    proposal_digest: Digest | None
    faults: tuple[AdmissionFault, ...]


AdmissionResult = AdmissionAccepted | AdmissionRejected
```

`Constructicon.validate(graph, inputs)` remains the strict Python convenience and raises `AdmissionError`. It delegates to the same implementation as the result-returning architect path.

### 1.5 Typed introspection contracts

Add `core/introspection.py`:

```python
DESCRIPTION_SCHEMA_VERSION = 1

class SchemaDocument(BaseModel):
    name: str
    version: int
    digest: Digest
    schema_: dict[str, JsonValue]

class ComponentDescription(BaseModel):
    name: str
    version: Digest
    stable: bool
    role: ComponentRole
    body_kind: Literal["atomic", "composite"]
    inputs: tuple[Port, ...]
    outputs: tuple[Port, ...]
    capability_requirements: tuple[CapabilityRequirement, ...]
    capability_contract_complete: bool
    loadability: Loadability
    labels: tuple[str, ...]

class CapabilityDescription(BaseModel):
    capability_id: str
    kind: str
    revision: str
    leased: bool
    requires_posture: Posture | None
    executor_profile: ExecutorProfile | None

class GrantVocabulary(BaseModel):
    postures: tuple[str, ...]
    network_values: tuple[str, ...]
    request_schema: SchemaDocument

class SystemDescription(BaseModel):
    schema_version: int = DESCRIPTION_SCHEMA_VERSION
    graph_schema: SchemaDocument
    admission_schema: SchemaDocument
    components: tuple[ComponentDescription, ...]
    capabilities: tuple[CapabilityDescription, ...]
    grants: GrantVocabulary
    total_components: int
    truncated: bool
```

Descriptions are generated directly from one `RegistrySnapshot`, the existing `CapabilityDescriptor` catalog, and Pydantic schemas. They never serialize the capability container, live objects, credentials, file handles, environment variables, or implementation closures.

## 2. SDK: thin sugar over canonical IR

### 2.1 One concrete authoring bundle, not another workflow model

Add a small concrete carrier:

```python
@dataclass(frozen=True)
class DefinitionBundle:
    definition: ComponentDef
    implementation: NodeImpl | None = None

    def ref(
        self,
        *,
        version: str | None = None,
        bind: Mapping[str, str] | None = None,
        grants: GrantRequest | None = None,
    ) -> Ref: ...
```

`DefinitionBundle` contains only the canonical `ComponentDef` and its process-local implementation. It has no nodes, edges, ports, loop policy, or serialization format of its own. It is consumed by:

1. `Constructicon.register(bundle)` at L4;
2. SDK combinators that immediately reduce it to `bundle.ref()`.

That is the I6 pair. Runtime and substrate never import it.

### 2.2 `@task`: signatures become component contracts

```python
@task(
    "example/triage",
    output="brief",
    capabilities=(CapabilityRequirement(alias="executor", kind="executor"),),
)
async def triage(issue: Annotated[Issue, port_type("example/Issue")]) -> BuildBrief:
    ...
```

Rules:

- explicit namespaced component name is required;
- ordinary parameters become input ports;
- a reserved `ctx: NodeContext` parameter is injected and is not a data port;
- no data parameters means a source;
- return `None` means a sink;
- one return value becomes one output named by `output=` (`"result"` default);
- multiple outputs require an explicit `outputs={name: annotation}` declaration and the function returns a mapping with exactly those names;
- `Annotated[T, port_type("namespace/Type")]` sets the nominal `type_id`;
- absent explicit metadata, type identity is derived deterministically from the Python annotation and is exposed in `describe()`;
- `T | None` compiles to cardinality `optional`;
- `list[T]` compiles to cardinality `many`;
- JSON Schema comes from Pydantic `TypeAdapter(T).json_schema()` and `schema_hash` follows the identity law;
- input values are validated into the annotated types before the function call;
- outputs are normalized through the canonical JSON wire function;
- sync and async functions are supported; sync tasks run inline and therefore must remain non-blocking—blocking OS work belongs in substrate capabilities;
- the generated runtime adapter is an ordinary importable `NodeImpl`, decorated with `functools.wraps`, so source identity remains bound to the original function; a constant SDK task-adapter revision participates in the component definition identity.

The decorator returns a `DefinitionBundle`. No decorated task is executable until registered and referenced like any other component.

### 2.3 `flow`: adjacency only

```python
pipeline = flow(
    "example/issue-to-summary",
    triage,
    summarize,
    publish,
    maps={
        "publish": {"brief": "triage.brief"},
    },
)
```

`flow()`:

- immediately creates a canonical `Graph` and wraps it in a composite `ComponentDef`;
- normalizes each step from `DefinitionBundle | Ref | str` to a `Ref`;
- creates exactly one `Connection` between adjacent steps;
- never resolves granular port bindings;
- accepts `maps` only as direct `Connection.map` authoring sugar;
- derives deterministic node IDs from component names, with stable numeric suffixes for duplicates; explicit `ids=` may override them;
- infers graph input/output contracts only when the relevant bundles are locally known; otherwise the caller supplies `inputs=` and `outputs=` explicitly;
- performs only Python-call-shape validation. Ref resolution, magnetic binding, grant checks, loop checks, and cycle checks remain exclusively in the runtime validator.

### 2.4 `harness`: semantic role, no new execution behavior

```python
repair_harness = harness(
    "example/repair-loop",
    loop(
        repair_body,
        feedback={"candidate": "candidate"},
        continue_from="continue",
        max_iterations=5,
    ),
    inputs=(GOAL, CANDIDATE),
    outputs=(CANDIDATE, EVALUATION),
)
```

`harness()` creates a `ComponentDef(role="harness", body=<canonical Graph>)`. It may wrap a `Ref`, `Graph`, or `Loop` in one deterministic graph node. “Harness” remains a semantic registry role only; the walker sees the same graph constructs.

### 2.5 Loop sugar is a direct constructor

```python
loop(
    body,
    feedback={"candidate": "candidate", "findings": "findings"},
    continue_from="continue",
    max_iterations=5,
) -> core.Loop
```

M5 loop sugar maps one-to-one onto M4’s generic `Loop`. It does not introduce:

- `until_gates`;
- gate-aware kernel semantics;
- a separate policy language;
- scope-lifetime worktrees;
- implicit repair or triage behavior.

Higher-level “until Ruff and Pytest pass” behavior remains an ordinary registered body graph containing gate and decision components. Candidate state travels as `GitRef` feedback through fresh invocation workspaces, exactly as M4 established.

### 2.6 Registration at L4

`Constructicon.register()` gains an API-layer overload:

```python
system.register(triage)       # DefinitionBundle
system.register(pipeline)     # DefinitionBundle
system.register(component_def, impl)  # existing form remains
```

The API unwraps the bundle and calls the existing runtime registry. The registry does not import the SDK.

## 3. `system.describe()`: the complete authoring contract

Replace the current untyped dictionary with:

```python
system.describe(
    *,
    component_names: Sequence[str] | None = None,
    limit: int = 100,
) -> SystemDescription
```

Rules:

- one immutable registry snapshot is used for the whole response;
- default output is bounded to 100 stable component contracts;
- `total_components` and `truncated` state what was omitted;
- explicit `component_names` requests those names directly and faults on unknown names;
- stable definitions are described by default; retained versions remain available through `describe_component(name, version=...)`;
- host-local loadability is reported truthfully;
- candidate version counts may be summarized, but complete registry browsing and stable cursors remain M6;
- Graph and AdmissionResult schemas are generated from the actual Pydantic types on every build, canonically hashed, and tested for stability;
- the grant vocabulary is generated from `GrantRequest`, `Posture`, and network literals;
- capability descriptions come only from the existing catalog;
- description order is deterministic by component name, version, and capability ID;
- `model_dump_json()` is the authoritative machine rendering; any human view is derived.

A component description provides exactly what an architect needs:

```text
name + stable version
semantic role
atomic/composite
input and output nominal contracts
required capability aliases and kinds
host loadability
available capability IDs and profiles
allowed grant vocabulary
```

No source code is required.

## 4. Architect-proposed Graph admission

Add one agent-facing method:

```python
system.admit_graph(
    proposal: Graph | Mapping[str, JsonValue] | str,
    inputs: Mapping[str, JsonValue],
) -> AdmissionResult
```

Pipeline:

```text
JSON string / mapping
    ↓ Graph.model_validate_json / model_validate
canonical Graph
    ↓ the existing admit(...)
ExecutionManifest or typed AdmissionFaults
```

Rules:

- there is no `ArchitectPlan`, collaboration plan, DSL, or alternate graph type;
- proposals may contain only what the existing Graph schema permits—registered references and nested canonical Graph/Loop values, never code;
- parse faults and semantic faults use one `AdmissionFault` schema;
- each submission takes a fresh atomic registry snapshot;
- the system does not mutate or auto-repair the proposal;
- a caller repairs its own JSON and resubmits;
- accepted output includes the exact canonical `Graph` and sealed manifest;
- `validate()` remains a strict wrapper over the same internal function;
- `start()` continues to use the same validation path—no “trusted SDK graph” bypass exists.

## 5. Validator refactor: repair-naming faults at the point of truth

Refactor `_Compilation.faults` from `list[str]` to `list[AdmissionFault]`. Every validator branch emits a stable code and structured details at the point where the facts are known.

Examples:

### Unknown reference

```json
{
  "code": "graph.reference.unknown",
  "repair": "replace the component name with a described component",
  "details": {
    "requested": "example/sumary",
    "available_components": ["example/summarize", "example/triage"]
  }
}
```

### Unpromoted component

```json
{
  "code": "graph.reference.unpromoted",
  "repair": "pin an exact retained version or promote one to stable",
  "details": {
    "registered_versions": ["sha256:..."],
    "stable": null
  }
}
```

### Missing capability binding

```json
{
  "code": "graph.capability.missing_binding",
  "repair": "add body.bind['workspace'] using a capability of kind 'workspace'",
  "details": {
    "alias": "workspace",
    "required_kind": "workspace",
    "available_capability_ids": ["git-workspace"]
  }
}
```

### Ambiguous port

The fault carries the exact candidates and a valid `Connection.map` example. It never chooses one.

Existing tests that regex-match `str(AdmissionError)` remain valid because messages are preserved. New tests pin codes, paths, repair text, and structured detail independently of prose.

## 6. Equivalence and the acceptance slice

### 6.1 SDK/direct equivalence

Re-express two existing worlds through the SDK:

1. the simple M1-style read pipeline, exercising `@task` and `flow`;
2. an M4 counter/refine loop, exercising `harness` and loop sugar.

For each world, construct the same graph by hand and through SDK sugar, then assert:

```python
sdk_graph.model_dump(mode="json") == direct_graph.model_dump(mode="json")
sdk_manifest.source_graph_hash == direct_manifest.source_graph_hash
sdk_manifest.world_hash == direct_manifest.world_hash
sdk_manifest.manifest_hash == direct_manifest.manifest_hash
```

The same assertion is run once against `InMemoryRegistryStore` and once against the SQLite-backed store. Sugar and storage choice cannot alter admitted meaning.

### 6.2 Architect repair round-trip

The acceptance test uses a deterministic `ScriptedArchitect` with this constructor only:

```python
ScriptedArchitect(
    system_description_json: str,
    graph_schema_json: str,
)
```

It receives no `Constructicon`, registry, source tree, component implementation, or Python object.

Scenario:

1. Register a small READ-only component catalog through the SDK.
2. Call `system.describe()` and serialize it.
3. The architect emits valid Graph JSON whose consumer input is ambiguous between two described producers.
4. `system.admit_graph()` returns `graph.port.ambiguous`, the two source addresses, and a `Connection.map` example.
5. The architect adds the map override and resubmits.
6. Admission returns `accepted` with a sealed manifest.
7. The graph executes successfully.
8. The repaired graph is equal to the equivalent hand-authored/SDK graph and has the same manifest hash.

This proves the entire M5 statement:

```text
schemas + describe + errors
    → invalid proposal
    → machine-readable rejection
    → JSON-only repair
    → accepted Graph
    → ordinary execution
```

## 7. Tests

### SDK

- source task from a zero-parameter function;
- sink task from `-> None`;
- sync and async task adaptation;
- optional and many cardinality inference;
- explicit nominal `type_id` metadata;
- canonical schema hashing;
- reserved `ctx` injection is not a port;
- single and explicit multi-output contracts;
- missing/extra multi-output values fail before checkpointing;
- decorated implementation reloads by `PythonRef` and source drift still refuses;
- deterministic flow node IDs and duplicate suffixing;
- `maps` compiles directly to `Connection.map`;
- harness role changes metadata only;
- loop sugar returns an actual `core.Loop`;
- SDK objects never appear in Graph JSON or manifests.

### Introspection

- in-memory and SQLite worlds produce byte-identical descriptions;
- descriptions are deterministically ordered;
- limit/truncated behavior is explicit;
- explicit component selection works;
- stable and exact-version component detail;
- loadability is truthful;
- capability container secrets and object reprs never appear;
- Graph schema digest is stable;
- every described component port/capability contract matches the stored definition/catalog;
- legacy capability-opaque definitions are labeled honestly.

### Admission faults

- malformed Graph JSON becomes `graph.schema.*` faults;
- unknown ref, unpromoted ref, missing/extra capability alias, kind mismatch;
- port absence, contract mismatch, ambiguity, and map repair details;
- grant widening and invalid loop controls;
- cycle and duplicate node errors;
- `str(AdmissionError)` remains readable and backward-compatible;
- JSON, mapping, and Graph inputs that represent the same proposal produce the same accepted manifest.

### Acceptance and regressions

- full scripted-architect reject → repair → accept → execute path;
- SDK/direct/proposed graph manifest equality;
- every pre-M5 test remains green;
- no journal schema migration;
- M1–M4 stored runs still resume and reproduce.

## 8. Files

```text
src/constructicon/core/component.py
    CapabilityRequirement; additive ComponentDef field and identity rule

src/constructicon/core/admission.py                 new
    AdmissionFault; AdmissionAccepted/Rejected/Result

src/constructicon/core/introspection.py             new
    SchemaDocument; component/capability/grant/system descriptions

src/constructicon/core/errors.py
    AdmissionError carries typed faults while preserving string rendering

src/constructicon/sdk/__init__.py
src/constructicon/sdk/task.py                       new
src/constructicon/sdk/combinators.py                new
src/constructicon/sdk/types.py                      new
    DefinitionBundle; @task; flow; harness; loop; annotation metadata

src/constructicon/runtime/validator.py
    typed fault emission; capability requirement enforcement

src/constructicon/runtime/registry.py
    public bounded component-description helpers over RegistrySnapshot/binding

src/constructicon/api/system.py
    register(DefinitionBundle); typed describe/describe_component; admit_graph

docs/adr/0011-agent-authoring-and-introspection.md  new
README.md / docs/ARCHITECTURE.md / AGENTS.md
    M5 complete; one authoring contract; SDK examples; repair loop

examples/read_pipeline.py                           new, executed
examples/architect_repair.py                        new, executed

tests/sdk/test_task.py                              new
tests/sdk/test_combinators.py                       new
tests/sdk/test_equivalence.py                       new
tests/api/test_describe.py                          new
tests/api/test_admit_graph.py                       new
tests/e2e/test_architect_repair.py                  new
```

## 9. Out of scope

- MCP transport, authentication, cursors, and request idempotency—M6;
- registry pagination and remote detail references—M6;
- channels, panel, human advisor, approval-driven unparking—M7;
- live Claude/Codex/Pi execution—M8;
- learning and dynamic skill routing—M9;
- automatic graph repair in runtime or API;
- a model call inside `admit_graph()`;
- YAML or another textual DSL;
- a serializable SDK AST;
- plugin discovery or entry points;
- nested loops;
- scope/run-lifetime workspaces;
- gate-aware loop syntax;
- a second component metadata store.

## 10. Verification

`uv run verify` remains the only gate and stays credential-free.

The M5 acceptance run is:

```text
Describe
→ Propose Graph JSON
→ Reject with typed faults
→ Repair JSON
→ Admit
→ compare with SDK/direct manifest
→ Execute
```

Final acceptance assertions:

```text
one published Graph schema
one canonical description derived from snapshot + catalog
one typed fault model from parse through semantic admission
one validator for SDK, direct JSON, and architect proposals
one manifest identity for equivalent authored intent
zero SDK semantics in runtime or walker
zero live authority serialized by describe
```
