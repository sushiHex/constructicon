# constructicon

An OS for agentic software-engineering pipelines. One authored graph IR, one
sealed `ExecutionManifest` per run, scoped capability leases, journal-minted
attestations, idempotent effects with receipts — and component versions that
reach dependents only through explicit promotion.

> Authored intent may be ergonomic; executed reality must be explicit.

Almost every concept reduces to four nouns: **Definition** (what may be
reused) · **Manifest** (what this run will execute) · **Invocation** (where
one execution occurred) · **Receipt** (what changed outside the run).

Agents are the first-class user — authoring graphs, operating runs, and
contributing code; humans participate as observer, advisor, and approver.

## Status

Architecture **frozen**; implementation at **M2** — the vertical slice plus
crash & resume hardening are green:

```
Graph → validate → ExecutionManifest → activate → claim (fenced lease)
      → FakeExecutor → checkpoint → idempotent effect → EffectReceipt
      → crash → reclaim → restore / reconcile → resume / reproduce → project
```

For every named hard-crash probe — including a real worker process dying via
`os._exit` — a fresh process reclaims the run with a higher ownership epoch,
the stale owner is fenced from all later writes, every committed checkpoint is
restored byte-for-byte, and no external effect ever happens twice.

The full lifecycle runs with zero credentials:

```bash
uv sync --dev
uv run verify        # ruff + mypy --strict + import-linter + pytest
```

## Documentation

- [docs/INVARIANTS.md](docs/INVARIANTS.md) — the thirteen laws and the never list
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — layers, IR, manifest, effects,
  registry, journal, milestones, failure tests
- [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) — extension guides (agents first)
- [docs/designs/SELF_IMPROVEMENT.md](docs/designs/SELF_IMPROVEMENT.md) —
  learning as candidates, never mutations
- [docs/adr/](docs/adr/) — why things are the way they are

## License

MIT — see [LICENSE](LICENSE).
