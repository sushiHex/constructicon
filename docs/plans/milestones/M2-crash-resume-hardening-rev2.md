# M2 — crash & resume hardening (rev 2, redlines incorporated)

## Context

M1 merged ([PR #1](https://github.com/sushiHex/constructicon/pull/1)); the
architecture is frozen. M2 is the durability layer:

```
Snapshot → Claim → Execute → Commit → Crash → Reclaim → Restore → Project
```

Rev 2 incorporates the seven approved redlines: fenced run leases (not PID
metadata), transaction-shaped journal operations with durable inputs,
write-once durable facts, snapshot-based registry admission with a separate
implementation-binding concern, a corrected fault-injection contract
(durably-checkpointed work only) with real process-death tests and a durable
fake external world, dependency blocking resolved before `_collect`, and
registry rows as receipts (no synthetic run events, no rollback sentinel).

**Acceptance criterion (replaces M1 plan's paragraph):** for every named
hard-crash probe, a new process over the same databases can atomically reclaim
the run with a higher ownership epoch; the stale owner is fenced from all later
writes; every committed checkpoint is restored byte-for-byte; uncommitted
invocation work may replay but is never mistaken for committed work; no
external effect occurs more than once; run state and terminal events agree
transactionally; admission sees one immutable registry snapshot; start, resume,
and reproduction all refuse unavailable or drifted implementations; JSONL and
summary projections regenerate canonically from one SQLite snapshot.

Pinned assertions: one live owner · one coherent component world · one
immutable checkpoint per invocation · one immutable receipt per effect
request · one terminal run transition · one canonical projection per journal
snapshot.

## 1. Fenced run ownership (`core/run.py`, new)

- `RunLease{run_id, owner_id, epoch, expires_at}` is the authority;
  `owner_pid/owner_host/heartbeat_at` columns are diagnostic only.
- **Every owner-side write is fenced** by `WHERE owner_id=? AND owner_epoch=?`.
  Unifying mechanism: every event-writing operation allocates its sequence by
  `UPDATE runs SET next_event_seq = next_event_seq + 1 WHERE run_id=? AND
  owner_id=? AND owner_epoch=?` inside the same `BEGIN IMMEDIATE` transaction —
  the seq allocation *is* the fence (also fixes M1's unguarded `MAX(seq)+1`).
  Zero rows updated ⇒ authority lost ⇒ the stale worker raises `OwnershipLost`
  and stops; it must not write anything else.
- Semantic operations (no exposed ownership columns): `claim_run(run_id,
  owner_id, ttl) -> RunLease` (atomic: accepts PENDING/FAILED/PARKED, accepts
  RUNNING only with an expired lease, increments epoch; two concurrent
  resumptions produce one winner), `heartbeat(lease, ttl)`,
  `release_run(lease)`, `request_cancel(run_id)`.
- **Continuous heartbeat**: one per-run asyncio task beating on an interval
  (default ttl 30s, beat 10s; test-tunable) while nodes and effects are in
  flight — never between-nodes-only, never appending events. Walker shape:
  claim → start heartbeat task → execute → finally stop heartbeat +
  release/terminally close.
- **Liveness ≠ lifecycle**: `RunStatus` keeps its six values; no persisted
  LOST. `RunState{status, liveness: live|lost|not_applicable}` is a read-time
  view — a lost run is durably RUNNING with an expired lease; `claim_run`
  reclaims it. PID death may accelerate the diagnosis; lease expiry is
  authoritative.

## 2. Transaction-shaped journal (`core/journal.py`, `substrate/journal/sqlite.py`)

- Semantic commits replace call-pairs: `create_run(run_id, manifest, inputs)`
  (txn 1: manifest-if-absent + PENDING run + **durable inputs** — new
  `inputs_json` on `runs`, ending M1's RunStarted-event archaeology);
  `claim_run(...)` + `transition_run(lease, *, expected: frozenset[RunStatus],
  target, event_kind, payload)` (fenced state change + event, one txn);
  `record_completion(lease, checkpoint)`; `record_effect_outcome(lease,
  request, receipt, event_kind)` (receipt + EffectCommitted/Reconciled event,
  one txn — closes an M1 seam). Crash between create and claim leaves a safely
  resumable PENDING run.
- **Write-once law for durable facts** (checkpoints, manifests, receipts,
  attestations, run creation): absent → insert; identical → idempotent return;
  contradictory at the same identity → `CheckpointConflict`/`JournalDamaged`.
  Replaces M1's `INSERT OR REPLACE` on checkpoints.
- **Resume behavior pinned**: PENDING → claim+start; RUNNING+live → refuse
  with owner detail; RUNNING+expired → reclaim (higher epoch); FAILED →
  claim + re-walk from checkpoints; PARKED → claim when condition satisfied;
  SUCCEEDED → return the materialized result, status untouched (covers crash
  after terminal commit, before caller return); CANCELLED → report cancelled,
  never silently restart.

## 3. Registry: snapshot, binding, activation (`core/registry.py` new)

- Three objects: **RegistryStore** (durable `StoredVersion{definition,
  content_hash, registered_at}` + promotion records; protocol in
  `core/registry.py` — one home per concept, not in journal.py; the in-memory
  store remains as the I6 test double), **RegistrySnapshot** (immutable,
  detached; one WAL read transaction; `admit()` consumes only this — the
  atomic-world test resolves A, mutates concurrently, resolves B, asserts one
  coherent pre-change world), **ImplementationBinding** (`BoundVersion{stored,
  impl, loadability}`; `Loadability{status: loadable|missing_module|
  missing_qualname|not_callable|implementation_drift|source_unavailable, …}`
  is host-local and never persisted — old versions stay valid definitions even
  where this host cannot execute them).
- **Registration validates identity**: recompute content + contract hashes,
  match `PythonRef.contract_hash`, require a concrete `source_digest` for
  persistable atomic versions (no `<locals>` closures, no None digests —
  ending M1's always-None `implementation_digest`).
- **One activation path**: `registry.activate(manifest) -> BoundExecution`
  verifies versions exist, atomics bind, observed digests equal the manifest,
  contracts match, capability revisions are assembled — used identically by
  start, resume, and reproduce (resume refuses drift too: a crash followed by
  a code update must not execute an old run's suffix on new code).
- **Fenced promotion**: compare-and-swap on `from_version == current stable`;
  one attestation authorizes one pointer move (unique constraint), so retries
  append nothing; `registration_seq`/`promotion_seq` INTEGER PRIMARY KEYs +
  `UNIQUE(name, content_hash)` — never timestamp ordering.
- `promote_initial` becomes idempotent: no pointer → promote; already stable
  at this exact version → return existing record; stable elsewhere → refuse.
- `Constructicon.describe()` moves off the private `_versions` dict onto a
  public `catalog()`/`names()` store query (rich introspection stays M5).

## 4. Fault injection — the corrected contract (`tests/`)

- **The durability statement**: no *durably checkpointed* invocation
  re-executes; work that finished only in memory before its completion
  transaction committed may execute again — nothing can preserve output that
  never reached the journal. Expected matrix pinned per crash point (before
  completion txn → may replay; after commit → restored; effect
  prepared/executed/receipted seams → reconcile-not-repeat; after terminal
  commit → return terminal result, never regress).
- **Probes inside the concrete store**: `_fault_probe("completion.
  after_checkpoint_insert" | "completion.after_event_insert" |
  "completion.after_commit" | effect and transition points…)` — a no-op hook a
  test can arm; a wrapper cannot reach intra-transaction seams.
- **Two lanes**: unit lane arms probes with `InjectedCrash(BaseException)` (a
  BaseException so the walker's `except Exception` cannot launder it into
  FAILED); acceptance lane runs a real worker subprocess
  (`tests/e2e/crash_worker.py`, probe chosen by env var) that dies via
  `os._exit` — no handlers, no finally, no connection cleanup — then a fresh
  process reclaims from durable state alone.
- **Durable fake external world**: the fake effect ledger and a fake executor
  call ledger move to a second SQLite file (`fake-external.db`) so recovery
  provably consults an independently durable "outside", and the parent
  asserts exactly which uncheckpointed work replayed.

## 5. Dependency blocking before `_collect` (`runtime/walker.py`)

- Walker tracks `status_by_path`; before invoking a destination: all expected
  producers completed → execute; all terminal with failures → mark BLOCKED and
  emit `NodeBlocked` carrying a typed `DependencyReport{destination,
  producers: tuple[ProducerStatus{path, status, error_ref}]}` listing *every*
  producer recorded in the manifest binding (completed ones included); not all
  terminal → not ready. Unrelated branches may finish; the run's terminal
  status is decided at graph closure.
- `_collect` stays strict: reaching it without every required completed value
  is kernel damage (internal contract violation), not execution state.

## 6. Projections + schema migration (`substrate/journal/projection.py` new)

- One read snapshot produces both `events.jsonl` (canonical_json per event, by
  seq) and `summary.json` (canonical_json; includes `schema_version`, run_id,
  `projected_through_seq`, status, manifest_hash, event_count, stored lease
  expiry — **no wall-clock, no derived liveness**: identical durable state ⇒
  identical bytes). Temp-file + atomic replace;
  `ProjectionResult{run_id, through_seq, events_digest, summary_digest}`;
  byte + digest comparison in tests. `Constructicon.project_run(run_id,
  out_dir)`.
- **`PRAGMA user_version` migrations**: explicit M1→M2 migration (new
  columns/tables can't come from `CREATE TABLE IF NOT EXISTS`).
  `tests/migrations/` fixture: build an exact M1-schema database with a
  completed and a failed run → open with M2 → verify migration → resume the
  failed run → project both — no M1 event or checkpoint lost.

## 7. Registry rows are receipts

- No synthetic run events for registration/promotion/rollback and no
  `run_id="bootstrap"` inventions: the `components` row *is* the
  ComponentRegistered receipt, the `promotions` row *is* the pointer-move
  receipt; a run event referencing the receipt id is appended only when a real
  `source_run` exists. (A global event stream waits for a real consumer.)
- **Remove the `"rollback"` sentinel before persistence**: rollback is an
  ordinary promotion of a retained older exact version — a deterministic
  rollback policy mints a normal attestation for the older version and goes
  through the same CAS path. No special rollback authority.
- `Attestation.created_by_run` becomes `RunId | None` (bootstrap policies have
  no run; never fabricate one).

## Files

- `src/constructicon/core/run.py` (new) — RunLease, RunState/liveness,
  OwnershipLost, CheckpointConflict.
- `src/constructicon/core/registry.py` (new) — RegistryStore protocol,
  StoredVersion, RegistrySnapshot, Loadability, BoundVersion contracts.
- `src/constructicon/core/journal.py` — semantic operations; write-once
  semantics; durable inputs; lease-fenced signatures.
- `src/constructicon/core/effect.py` — `created_by_run: RunId | None`.
- `src/constructicon/runtime/registry.py` — logic over injected store;
  snapshot-consuming resolve; `activate()`; CAS promote; idempotent
  `promote_initial`; rollback-as-promotion.
- `src/constructicon/runtime/validator.py` — consumes RegistrySnapshot;
  populates `implementation_digest`.
- `src/constructicon/runtime/walker.py` — claim/heartbeat/release lifecycle;
  fenced writes via the journal ops; activation on start/resume/reproduce;
  status_by_path + BLOCKED reporting; SUCCEEDED/CANCELLED resume semantics.
- `src/constructicon/substrate/journal/sqlite.py` — the SQLite store owns the
  database and every transaction boundary: migrations (user_version), new
  tables/columns, fenced seq allocation, write-once inserts, fault probes,
  RegistryStore implementation; `projection.py` (new).
- `src/constructicon/api/system.py` — persistent-store assembly,
  `cancel(run_id)`, `project_run(...)`, describe() via public catalog query.
- `tests/` — `core/test_run_lease.py`, `runtime/test_snapshot.py` +
  `test_activation.py`, `e2e/test_fault_injection.py` + `crash_worker.py`,
  durable fake-external ledger in conftest, `migrations/test_m1_to_m2.py`,
  blocking-report tests, projection byte/digest tests; existing 26 tests stay
  green (updated only where signatures changed).

Reuse: identity law (`core/identity.py`) for all new digests; ExecutionPath
checkpoint keys; the effect boundary semantics (now committed atomically with
their events); `uv run verify` remains the single gate; CI unchanged.

## Out of scope

Git authority (M3) · loops (M4) · SDK/describe-rich (M5) · MCP (M6) ·
channels (M7) · live executors (M8) · learning (M9). No IR changes; additive
schema only, behind the user_version migration.

## Verification

- `uv run verify` — all lanes credential-free.
- Acceptance: the subprocess crash suite passes at every named probe with the
  pinned matrix; two concurrent resumptions of one run yield one winner and
  one fenced loser; the M1-fixture migration test passes; a second
  `Constructicon` over the same files resumes/reproduces the first's runs and
  refuses a deliberately drifted implementation on *both* resume and
  reproduce; projections are byte-identical across regeneration.
