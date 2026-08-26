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

Architecture **frozen**; implementation through **M4** is green — the vertical
slice, crash & resume hardening, git authority, and generic bounded loops:

```
Stage → Import → Prepare exact merge → Gate (read-only, real Ruff/Pytest)
      → red → repair in a fresh frame-stamped workspace → gate green
      → journal-minted Attestation → merge_verified → one git ref transaction
      → Receipt → crash → reconcile / restore by ExecutionPath → resume
```

The strongest claim is mechanically true and tested: **the only path from
proposed code to a protected git ref is one exact, attested, idempotent git
transaction.** Agent workspaces are staging repositories with zero authority
refs; a moved base is a truthful rejected receipt; forged, absent,
mismatched, failing, or world-mismatched attestations move nothing; every
hard-crash probe — including a real worker dying via `os._exit` mid-merge —
recovers to exactly one install.

Loops add no scheduler and no gate-aware kernel object. Admission seals their
initial bindings, feedback edges, canonical boolean control, exports, and
atomic member order. Every iteration is a distinct `ExecutionPath`, so
checkpoints, effects, and capability leases reuse the existing recovery laws.
False exports the final completed state; all-true exhaustion becomes
`PARKED/policy_exhausted` at graph closure. The acceptance path turns a broken
Git candidate red→repair→green across fresh staging repositories and installs
one exact verified merge.

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
