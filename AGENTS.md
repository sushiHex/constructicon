# Constructicon — agent contributor guide

Agents are this repository's first-class contributor. Everything you need is
three documents and one command:

- `docs/INVARIANTS.md` — the thirteen laws, the four-noun kernel, the never
  list. Read first; a change that violates one is wrong even if it works.
- `docs/ARCHITECTURE.md` — the current truth: layers, IR, manifest, effects,
  registry, journal, milestones, failure tests.
- `docs/CONTRIBUTING.md` — one page per extension kind.

```bash
uv run verify        # ruff + mypy --strict + import-linter + pytest — what CI runs
```

## The map

```
src/constructicon/
├── core/        L0 — every contract, defined once (stdlib + Pydantic only)
├── substrate/   L1 — implementations: executors, journal, effects (gates,
│                     workspace, channels arrive with M3/M7)
├── runtime/     L2 — registry, validator -> ExecutionManifest, walker
│                     (imports core contracts only — never substrate)
├── sdk/         L3 — authoring sugar (arrives with M5)
└── api/         L4 — the system object; assembles substrate into runtime
tests/           mirrors the layers + e2e/ (the vertical slice)
docs/adr/        history by reference — why things are the way they are
```

## Rules that bite

- **Compose before you drop a tier.** Check for an existing component or
  contract before writing a new one; new primitives need a reason.
- **The walker decides nothing.** If your change makes the walker resolve,
  search, inherit, choose, or judge safety at runtime, it belongs in the
  validator or an effect adapter instead.
- **Registration never propagates.** Only promotion moves a pointer, and only
  with a journal-minted attestation.
- **Truthful telemetry.** `None` over inferred; partial over dropped; demoted
  over false-ok. State guarantees at their real strength.
- **No credentials in tests.** The full lifecycle runs fake-first; recorded
  transcripts test drivers.
- **Frozen decisions stay frozen.** The never list and the ADRs are not
  reopened because an implementation detail feels inconvenient — make the
  implementation satisfy the invariant.
