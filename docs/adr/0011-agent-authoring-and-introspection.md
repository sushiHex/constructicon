# 0011 — Agent-first authoring and introspection

**Status:** accepted (M5)

## Decision

M5 makes Constructicon authorable without adding a workflow language.

Every authoring surface converges immediately on the frozen three-construct IR:

```text
Python SDK sugar ─┐
                  ├─→ strict Graph → one validator → ExecutionManifest
Architect JSON ───┘
```

`DefinitionBundle` is a process-local registration convenience containing one
canonical `ComponentDef` and an optional atomic implementation. It is never
serialized, admitted, journaled, or interpreted by the walker. `@task`,
`component`, `flow`, `harness`, and loop sugar emit only existing core objects.
Equivalent SDK and direct authoring must produce byte-equivalent Graph JSON and
identical manifest identities under the same registry snapshot and inputs.

## Task contracts

`@task` lowers a module-level typed Python function into:

- nominal, schema-hashed input and output ports;
- an importable async `NodeImpl` adapter installed under a deterministic module
  global;
- a `PythonRef` whose digest covers the unwrapped user source and the SDK adapter
  revision;
- an explicit capability requirement tuple, including `()` for a complete
  declaration of no capabilities.

Historical definitions use `capability_requirements=None`, meaning the contract
predates declaration and is capability-opaque. This is distinct from an
explicitly empty declaration. Legacy definitions retain the M1-M4 component
identity algorithm; complete M5 contracts use the next identity version and
include sorted capability requirements.

Input lowering is exact: `T` is cardinality one; `T | None` is optional;
`list[T]` is a many-valued gathering input whose port schema is the producer
schema for `T` while its adapter validates `list[T]`. An output `list[T]` remains
one list payload. Defaults, `Any`, variadic parameters, positional-only
parameters, unresolved annotations, and unions beyond `T | None` are rejected
because they would introduce SDK-only behavior invisible to the Graph.

## Strict architect admission

Canonical Graph models reject unknown fields and unsupported schema versions.
Node identifiers beginning with `$` are compiler-reserved. `admit_graph()`
accepts Graph objects, mappings, or JSON text; parses strictly; enforces bounded
proposal, depth, node, fault, and detail limits; then enters the same validator
used by direct and SDK authoring.

Expected rejection is data:

```text
AdmissionFault{code, message, path, scope, repair, details}
AdmissionAccepted{graph, manifest}
AdmissionRejected{graph?, faults}
```

Parse and semantic faults share one versioned result schema. Semantic rejection
returns the canonical parsed Graph so an architect repairs normalized data.
Accepted manifests are previews for inspection, never public execution tokens;
`system.start(graph, inputs)` re-admits the Graph before execution.

Constructicon does not auto-repair proposals. A caller receives deterministic,
bounded, itemized faults and resubmits explicitly.

## Introspection

`system.describe()` is a derived, secret-free projection over exactly:

```text
one RegistrySnapshot
+ the assembled CapabilityDescriptor catalog
+ live capability availability
+ the effective root grant ceiling
+ canonical authoring constants and schemas
```

No metadata store, skill registry, or live capability serializer is added.
Descriptions include stable component contracts, schema completeness,
capability requirements, capability availability, root grants, magnetic binding
and selector vocabulary, the canonical continuation contract, authoring limits,
and content identities for the registry snapshot, catalog, and full description.
Port schemas are deduplicated by schema hash.

Legacy components remain describable but are marked honestly as port-schema or
capability-contract incomplete where applicable.

## Consequences

An architect using only serialized `SystemDescription` and serialized rejection
results can author an invalid Graph, repair its JSON shape, repair a semantic
ambiguity through the returned `Connection.map` path and selector, admit the
result, and execute it. No source code, registry object, implementation closure,
or live capability object is required.

MCP transports this same contract in M6; it does not redefine it.
