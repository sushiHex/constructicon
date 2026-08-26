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

Implement `constructicon.core.effect.EffectAdapter`: declare
`native_idempotency` or `reconcilable` recovery (an effect that is neither is
not admittable), honor the computed idempotency key, and implement
`reconcile`. Never make an adapter that blindly re-executes.

## Adding a channel transport (L1, M7)

Typed envelopes only (I5); message identities derive from invocation ids;
durable sends commit through the journal transaction or the effect boundary.

## Kernel changes (L0/L2)

Require an invariant review against `docs/INVARIANTS.md` and, for anything the
plan calls frozen, an ADR in `docs/adr/`. The import-linter layer contract and
the kernel dependency budget (stdlib + Pydantic) are CI law.
