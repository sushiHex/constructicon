# Constructicon — agent contributor guide

Agents are this repository's first-class contributor. Everything you need is
three documents and one command:

- `docs/INVARIANTS.md` — the thirteen laws, the four-noun kernel, the never
  list. Read first; a change that violates one is wrong even if it works.
- `docs/ARCHITECTURE.md` — the current truth: layers, IR, authoring contract,
  manifest, effects, registry, journal, milestones, failure tests.
- `docs/CONTRIBUTING.md` — one page per extension kind.

```bash
uv run verify        # ruff + mypy --strict + import-linter + pytest — what CI runs
```

## The map

```
src/constructicon/
├── core/        L0 — every contract, defined once (stdlib + Pydantic only)
├── substrate/   L1 — executors, journal, effects, git authority, gates
├── runtime/     L2 — registry, typed authoring preflight, validator → manifest,
│                     walker (imports core contracts only — never substrate)
├── sdk/         L3 — @task + component/flow/harness/loop authoring sugar
└── api/         L4 — system.describe/admit_graph/control + injection root
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
- **Registration never propagates.** Only promotion moves a pointer, and only
  with a journal-minted attestation.
- **Truthful telemetry and contracts.** `None` over inferred; partial over
  dropped; legacy opaque over invented completeness; demoted over false-ok.
- **No credentials in tests.** The full lifecycle runs fake-first; recorded
  transcripts test drivers.
- **Frozen decisions stay frozen.** The never list and ADRs are not reopened
  because an implementation detail feels inconvenient — make the implementation
  satisfy the invariant.
