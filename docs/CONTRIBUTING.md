# Contributing

The expected contributor is an agent (I9). One command verifies everything CI
checks:

```bash
uv run verify        # ruff + mypy --strict + import-linter + pytest
```

Green locally is the goal `verify` serves; CI runs the same command. The full
lifecycle runs with zero credentials (I7) — if your change needs a secret to be
tested, the design is wrong.

Before writing anything new, inspect `system.describe()` and check for an
existing component or contract to compose or extend. Use
`describe_component(name)` for one stable contract and `rdeps(name)` before
changing a shared definition. Compose before you drop a tier (I10).

## Authoring components and graphs (L3/L4)

- Use `@task("namespace/name")` for a new atomic operation. Every data
  parameter and return value needs a concrete annotation; use
  `Annotated[T, port_type("namespace/Type")]` when the Python class name is not
  the intended public nominal identity.
- `T | None` is an optional input. `list[T]` is a gathering input whose Graph
  contract remains `T`; an output `list[T]` is one list payload. Defaults,
  `Any`, variadic parameters, positional-only parameters, and `list[T] | None`
  are rejected because they would add Python-only semantics the Graph cannot
  see.
- Declare atomic capability aliases with `CapabilityRequirement(alias, kind)`.
  Bind an assembled capability id explicitly on the `Ref`; combinators never
  choose one by kind.
- Use `component`, `flow`, `harness`, and `loop` only as sugar. The produced
  definition must contain the same `Ref | Graph | Loop` you would hand-author.
  Add an equality test against the direct Graph for new combinator behavior.
- Architect JSON enters through `system.admit_graph()`. It is strict and bounded;
  rejection is a versioned `AdmissionRejected` with itemized repair data. Never
  add automatic repair or a trusted-SDK bypass. Public execution calls
  `system.start(graph, inputs)`, which admits again.

## Adding a control operation (L0/L4)

A mutating control operation belongs in the transport-neutral `ControlPlane`,
not inside MCP or a future CLI.

1. Define or reuse a typed response in `core/control.py`.
2. Require the exact actor scope before command claiming.
3. Canonicalize the request and require a bounded caller idempotency key.
4. Claim the command through `ControlStore`.
5. Store every decision needed after a crash in the immutable command plan.
6. Apply or reconcile exactly one durable domain mutation.
7. Complete or reject the command with the exact response that retries replay.

Every new mutation needs fault-injection coverage at all three seams:

```text
after plan commit, before domain mutation
after domain mutation, before command completion
after command completion, before response delivery
```

Retrying the same actor, operation, key, and request must create exactly one
domain fact. Reusing the key with different arguments must be a typed conflict
and perform nothing.

`RunHost` is not a scheduler. It owns only process-local run worker coroutines,
a concurrency ceiling, PENDING/lost-RUNNING recovery, and abandon-on-shutdown.
The walker remains the only scheduler of graph units.

## Adding an MCP tool or resource (L4 only)

The optional MCP package lives under `constructicon.api.mcp`; no other module may
import `mcp`.

- The handler derives `AuthenticatedActor` from its `ActorSource`, delegates
  once to `ControlPlane`, and returns the typed result.
- Do not open SQLite, compute identities, interpret cursors, select registry
  versions, or implement recovery in the handler.
- Do not accept actor identity in arguments. Stdio receives a trusted static
  actor; HTTP receives an actor derived from a verified OAuth access token.
- Keep malformed Graph proposals as generic JSON until they enter
  `system.admit_graph()`, preserving M5's strict parser and repairable faults.
- Return bounded summaries and `DetailRef`s. Full immutable records remain in the
  authoritative stores and are read through `constructicon://` references.
- Use the official MCP in-memory client in credential-free tests. Add a fake
  token-verifier lane for HTTP identity or scope behavior.

Tool annotations are client hints, never authorization. Actual authority is the
actor scope plus existing Constructicon admission/effect rules.

## Counterfactual execution

Counterfactual replay is deliberately narrower than general graph migration:

- the source topology and every non-overridden scope remain exact;
- overrides name exact retained component versions and must preserve the source
  contract at every affected scope;
- live effect identities remain unchanged, while simulated effects use their own
  namespace and `EffectAdapter.simulate()`;
- a counterfactual boundary must never call `execute()` or `reconcile()` on an
  external effect adapter;
- mutable capability acquisitions close with `discard`, even after successful
  invocation;
- source run, override set, effect mode, and capability mode are recorded in
  `RunOrigin`.

An adapter that cannot simulate truthfully declares simulation unsupported and
causes admission/control refusal before external I/O.

## Adding an executor (L1)

1. Implement the `constructicon.core.executor.Executor` protocol: `profile`
   (including an honest `IsolationProfile` — admission rejects postures the
   executor cannot mechanically enforce; never overstate), `validate_grants`,
   and `execute` returning a discriminated `ExecutorOutcome`.
2. Truthful telemetry is law (I4): fields the backend does not emit stay
   `None`; damaged streams return `ExecutorPartial`; timeouts salvage partial
   output into `ExecutorFailure`.
3. Tests: recorded transcripts, argv capture, damaged-stream demotion — no
   live calls in CI. Copy `substrate/executors/fake.py` as the shape.

## Adding a gate / check producer (L1)

Implement `CheckResult` production over a workspace; the runner mints the
`Attestation`. A red check is data, not an error.

## Adding an effect adapter (L1)

Implement `constructicon.core.effect.EffectAdapter`:

- declare `native_idempotency` or `reconcilable` recovery; an effect that is
  neither is not admittable;
- honor the computed live idempotency key and implement `reconcile()`;
- declare whether simulation is supported and, when supported, implement
  `simulate()` without external mutation;
- never make an adapter that blindly re-executes an unknown external outcome;
- never return `committed` for simulation — use the truthful `simulated` status.

## Adding a channel transport (L1, M7)

Typed envelopes only (I5); message identities derive from invocation ids;
durable sends commit through the journal transaction or the effect boundary.

## Kernel changes (L0/L2)

Require an invariant review against `docs/INVARIANTS.md` and, for anything the
plan calls frozen, an ADR in `docs/adr/`. The import-linter layer contract and
the kernel dependency budget (stdlib + Pydantic) are CI law.
