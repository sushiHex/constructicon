# M2 — crash & resume hardening (persistent registry, fault injection, cancellation, projections)

## Context

M1 merged to `main` ([PR #1](https://github.com/sushiHex/constructicon/pull/1)):
the vertical slice is green end-to-end with a sealed `ExecutionManifest`,
checkpoint resume, and the idempotent effect boundary. The architecture is
frozen (`docs/INVARIANTS.md`, `docs/ARCHITECTURE.md`, `docs/adr/`); per its
build order the next milestone is **M2**, whose acceptance criterion is:

> Scripted kills anywhere lose no completed computation and never misidentify
> node instances.

M1 deliberately left four gaps M2 closes: the registry is in-memory (a restart
loses definitions and promotions), fault injection covers only the
effect-vs-receipt boundary, there is no cancellation or lost-run detection, and
the journal has no JSONL projections. Four rows of the non-negotiable
failure-test table (docs/ARCHITECTURE.md) belong to M2: atomic-world
resolution, crash-between-event-and-checkpoint, gather-producer-failure
reporting, and reproduction-refuses-on-digest-mismatch.

## 1. Persistent registry (SQLite, same authoritative store)

Move `ComponentRegistry` storage into the existing journal database
(`src/constructicon/substrate/journal/sqlite.py` owns the connection; the
registry gains a storage backend injected at assembly per I8 — runtime still
never imports substrate):

- New tables: `components(name, content_hash PK-part, definition_json,
  registered_at)` and `promotions(id, component, channel, from_version,
  to_version, attestation_id, actor, source_run, created_at)` — append-only.
- `constructicon/core` gains a small `RegistryStore` protocol (I6's second
  consumer: the in-memory store remains as the test double); the SQLite
  implementation lives in substrate; `ComponentRegistry`
  (`src/constructicon/runtime/registry.py`) becomes logic over the store.
- **Implementations rebind at load**: definitions persist; atomic impls are
  re-bound at assembly by resolving each `PythonRef` (module + qualname import)
  and verifying `source_digest_for(impl)` against the recorded digest — a
  mismatch marks the version "not loadable: implementation drift" rather than
  silently substituting (I4).
- **Atomic-world resolution**: `admit()` takes its full resolution under one
  read snapshot (single connection/transaction) so a concurrent registration or
  promotion cannot split a run's world (failure-test row: Registry).
- `ComponentResolution.implementation_digest` (currently always `None` —
  `src/constructicon/runtime/validator.py`) gets populated from the version
  record; **reproduce refuses** when the installed digest differs from the
  recorded one (failure-test row: Reproduction).
- Registry mutations journal events: `ComponentRegistered`,
  `ComponentPromoted`, `ComponentRolledBack` (the rollback event M1 stubbed in
  `ComponentRegistry.rollback`).

## 2. Fault injection at every completion boundary

- Test-only `FaultyJournal` wrapper (in `tests/`, wrapping the real
  `SqliteJournal`) that raises at scripted points: before the
  checkpoint transaction, after commit but before the caller returns, between
  `record_effect_prepared` and adapter execution, between adapter execution and
  `record_effect_receipt` (extends the existing e2e crash test), and during
  run-status transitions.
- Parametrized e2e suite (`tests/e2e/test_fault_injection.py`): for every
  scripted kill point — run, crash, resume with a fresh `Walker` +
  fresh `SqliteJournal` handle over the same file — assert: no completed node
  re-executes (FakeExecutor call count), no effect duplicates
  (FakeAnnounceEffect executions), outputs identical, and the journal's event
  stream stays truthful (no `NodeCompleted` without its checkpoint row —
  crash-between-event-and-checkpoint row of the failure table).
- The transactional guarantee under test already exists
  (`SqliteJournal.record_completion`); the suite proves it and pins it.

## 3. Cancellation and lost detection

- `runs` table gains `owner_pid`, `owner_started_at`, `heartbeat_at`; the
  walker heartbeats between nodes.
- **Cooperative cross-process cancel**: `journal.request_cancel(run_id)` sets a
  flag; the walker checks it between nodes and on effect boundaries, finalizes
  leases, sets `CANCELLED`, and raises `Cancelled`. In-process cancel = asyncio
  cancellation wrapped to the same path.
- **Lost detection resolved on read** (hardline's rule): a run in `RUNNING`
  whose owner pid is dead / heartbeat stale is reported `LOST` by status
  queries, never silently left running; `resume()` on a lost run reclaims it.
- Node records use the canonical `InvocationStatus` for
  cancelled/lost/blocked/skipped in events.
- **Gather termination** (failure-test row): when a producer fails, the walker
  fails dependents with a complete producer-status report (which producers
  completed/failed/skipped) instead of a bare missing-value error — replaces
  the current `ContractViolation` in `_collect`
  (`src/constructicon/runtime/walker.py`).

## 4. JSONL projections

- `constructicon/substrate/journal/projection.py`: regenerate per-run
  `events.jsonl` + `summary.json` from SQLite (one direction only — SQLite is
  authoritative; projections are disposable and rebuildable).
- `Constructicon.project_run(run_id, out_dir)` on the system object
  (`src/constructicon/api/system.py`).
- Test: project → delete → regenerate → byte-identical.

## Files

- `src/constructicon/core/journal.py` — RegistryStore protocol, cancel/heartbeat
  additions to the Journal protocol, run-status query semantics for LOST.
- `src/constructicon/runtime/registry.py` — logic over injected store; drift
  marking; registry events.
- `src/constructicon/runtime/validator.py` — snapshot resolution;
  implementation_digest population.
- `src/constructicon/runtime/walker.py` — heartbeats, cancel checks, lease
  finalization on cancel, gather failure reports, reproduce digest check.
- `src/constructicon/substrate/journal/sqlite.py` — new tables + store impl +
  cancel/heartbeat; `projection.py` new.
- `src/constructicon/api/system.py` — assembly of the persistent store;
  `cancel(run_id)`, `project_run(...)`.
- `tests/` — `FaultyJournal`, `tests/e2e/test_fault_injection.py`,
  `tests/runtime/test_persistence.py` (registry survives restart; drift
  refusal; atomic world), cancellation/lost tests, projection test.

Reuse throughout: the identity law (`core/identity.py`), `ExecutionPath`
checkpoint keys, the effect boundary (unchanged), `verify`.

## Out of scope (later milestones, unchanged)

Git authority/gates (M3) · loops (M4) · SDK + describe (M5) · MCP (M6) ·
channels/panel (M7) · live executors (M8) · learning (M9). No new IR
constructs, no schema-breaking changes to M1's tables (additive columns only).

## Verification

- `uv run verify` stays the single gate; all new tests are credential-free.
- The M2 acceptance run: the fault-injection suite passes at every scripted
  kill point; registry persistence proven by constructing a second
  `Constructicon` over the same database file and resuming/reproducing runs
  registered by the first, including one refusal on deliberate source drift.
- CI (`.github/workflows/verify.yml`) runs it all on the PR.
