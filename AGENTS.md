# Constructicon — agent contributor guide

Agents are this repository's first-class contributor. Everything you need is
three documents and one command:

- `docs/INVARIANTS.md` — the thirteen laws, the four-noun execution kernel,
  and the never list. Read first; a change that violates one is wrong even if
  it works.
- `docs/ARCHITECTURE.md` — the current truth: layers, IR, authoring contract,
  durable control plane, manifest, effects, registry, journal, milestones, and
  failure tests.
- `docs/CONTRIBUTING.md` — one page per extension kind.

```bash
uv run verify        # ruff + mypy --strict + import-linter + pytest — what CI runs
```

## The map

```text
src/constructicon/
├── core/        L0 — every contract, defined once (stdlib + Pydantic only)
├── substrate/   L1 — executors, journal/control store, effects, git, gates
├── runtime/     L2 — registry, typed authoring preflight, validator → manifest,
│                     walker (imports core contracts only — never substrate)
├── sdk/         L3 — @task + component/flow/harness/loop authoring sugar
└── api/         L4 — system object, ControlPlane, RunHost, cursor/detail logic,
                      optional MCP adapter, and the injection root
tests/           mirrors the layers + credential-free e2e acceptance lanes
docs/adr/        history by reference — why things are the way they are
```

## Rules that bite

- **Inspect before inventing.** Use `system.describe()` for stable components,
  schemas, capabilities, root grants, and authoring vocabulary before creating
  a primitive. Use `describe_component()` and `rdeps()` for detail and impact.
- **One Graph language.** SDK combinators and raw JSON must produce the same
  strict `Graph` and pass the same validator. No SDK AST, hidden default,
  automatic repair, or alternate workflow representation.
- **Compose before you drop a tier.** Check for an existing component or
  contract before writing a new one; new primitives need a reason.
- **The walker decides nothing.** If your change makes the walker resolve,
  search, inherit, choose, or judge safety at runtime, it belongs in admission
  or an effect adapter instead.
- **MCP is a skin.** Durable authority lives in `ControlPlane`, `ControlStore`,
  the journal, registry, and effect adapters. An MCP handler derives its actor,
  delegates once, and returns the typed result. It never opens SQLite, computes a
  `RunId`, interprets a cursor, or reconciles a command.
- **One durable command law.** Every mutation takes a caller idempotency key and
  follows `authorize → claim → plan → apply once → record → replay`. Add fault
  tests after plan commit, after domain mutation, and after command completion.
- **One RunId, one scheduler.** `RunHost` owns process-local worker coroutines and
  restart recovery only. It never schedules graph units; the walker remains the
  sole graph scheduler. Server shutdown abandons work without inventing user
  cancellation.
- **Counterfactual means simulated.** It pins the source world except exact,
  contract-compatible overrides. Effect adapters use a separate simulated
  identity and `simulate()`, never `execute()` or `reconcile()`; mutable
  capabilities close with `discard`.
- **Actors come from transports.** Stdio receives a trusted fixed actor; HTTP
  receives a verified OAuth actor. Never add `actor_id`, `user`, or similar
  caller-controlled identity fields to tools.
- **Registration never propagates.** Only promotion moves a pointer, and only
  with a journal-minted attestation whose baseline still equals current stable.
- **Truthful telemetry and contracts.** `None` over inferred; partial over
  dropped; legacy opaque over invented completeness; simulated over false
  committed; demoted over false-ok.
- **No credentials in tests.** The full lifecycle runs fake-first; recorded
  transcripts test drivers. MCP tests use the official in-memory client and a
  fake token verifier where HTTP identity matters.
- **Frozen decisions stay frozen.** The never list and ADRs are not reopened
  because an implementation detail feels inconvenient — make the implementation
  satisfy the invariant.
