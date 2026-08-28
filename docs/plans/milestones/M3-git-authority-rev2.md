# M3 — git authority (rev 2, both blocking redlines + five refinements incorporated)

## Context

M1 and M2 are merged; the architecture is frozen. M3 realizes I1/I2 in git:
**read-only snapshots, WRITE worktree leases, Pytest/Ruff gates,
exact-merge-tree attestations, discard-on-failure** — LLMs propose; code
validates, executes, disposes.

```
Stage → Import → Prepare → Verify → Attest → Transact → Receipt → Reconcile
```

Rev 2 incorporates the review's redlines: (1) a **staging-repository
boundary** so no agent workspace is ever a linked worktree of the authority
repository (linked worktrees share `refs/*` — an agent could
`git update-ref` the authority branch directly, and "one install path" would
be false); (2) a **complete typed `MergeSubject`** binding
`{repository, target_ref, candidate, expected_base, merge_commit,
tested_tree}` — the attestation authorizes that exact commit into that exact
ref, with object-integrity checks demoted to defense in depth; plus atomic
effect **marker refs** replacing reflog reconciliation, **physical
acquisition epochs** fencing workspaces (not just journal rows),
**journal-computed attestations** minted from drafts with manifest-bound
effect requests, **pinned git/gate environments**, and **calibrated
rejection/isolation semantics**.

**Acceptance criterion:** a run receives a WRITE workspace whose git
repository is physically separate from the authority repository and derived
from one exact target-ref base; agent-authored git commands can alter only
that staging repository. Deterministic code imports the committed candidate
into the authority repository, prepares one canonical
`MergeSubject{repository, target_ref, candidate, expected_base,
merge_commit, tested_tree}`, and runs real Ruff and Pytest against a fresh
read-only snapshot of that exact merge commit. The journal mints an
attestation binding the complete subject, check-set identity, and sealed
manifest. `merge_verified` verifies exact subject equality plus git object
integrity, then atomically CAS-updates the target ref and creates an
idempotency marker ref in one git transaction. A crash after installation
recovers from that marker without repeating the install. A moved base
produces a durable rejected receipt; forged, absent, mismatched, failing, or
world-mismatched attestations produce no git transition and no terminal
receipt. Every physical acquisition is fenced by the run ownership epoch, so
a stale worker cannot touch a reclaimed workspace. Terminal cleanup is
CAS-safe and fully reconcilable. `uv run verify` stays credential-free.

Pinned assertions: one protected authority repository · one complete typed
merge subject · one journal attestation minter · one git ref transaction per
install · one durable external marker per committed effect · one physical
workspace per ownership epoch · one terminal receipt per idempotency key ·
zero protected-ref authority in an agent workspace.

## 1. Core contracts (`core/effect.py`, `core/workspace.py` new)

- **`MergeSubject`** (frozen, `kind="git_merge"`): `repository`,
  `target_ref` (always fully qualified — `refs/heads/main`, never
  shorthand), `candidate: GitSha`, `expected_base: GitSha`,
  `merge_commit: GitSha`, `tested_tree: GitSha`. It replaces the
  incomplete, consumer-less `GitProofSubject` in the `ProofSubject` union
  and is used identically by `PreparedMerge`, `Attestation.subject`, the
  effect subject dict, idempotency, reconcile, and receipts — one subject
  everywhere. Arbitrary target refs are first-class (run branches later;
  never silently `main`).
- **`CheckResult`** gains `status: Literal["passed", "failed", "conflict",
  "timeout", "cancelled", "infrastructure_error"]`; `ok` stays but a model
  validator derives each from the other so M1/M2 attestation JSON still
  loads (missing status ⇒ passed/failed from ok; present ⇒ must agree). A
  missing executable is not a failing test.
- **`AttestationDraft`** (action, subject, checks, check_set_hash,
  evidence, manifest_hash, workspace_id) — what callers may author.
  `Attestation` itself is journal-computed (see §6).
- **`EffectRequest`** gains `run_id` + `manifest_hash`, supplied by the
  walker's effect boundary — never by the node. The idempotency-key
  formula is unchanged (manifest_hash was already in it).
- **`core/workspace.py`**: `WorkspaceView` protocol (`path`,
  `git_ref() -> GitRef`), `WriteWorkspace` adds
  `commit_all(message) -> GitSha`; async **`LeasedCapability`** protocol —
  `acquire(LeaseContext) -> AcquiredCapability` (resource + lease_id +
  acquisition_id + resource_ref), `close(acquisition, disposition:
  release|discard|suspend) -> LeaseClosure`, `reconcile(LeaseContext)`.
  `LeaseContext` carries run_lease, binding, path, manifest_hash. The
  walker knows these verbs, never git. Identity is computed:
  `lease_id = digest("capability-lease", 1, {run_id, scope, binding})`,
  `acquisition_id = digest("capability-acquisition", 1, {lease_id,
  owner_epoch})` — **a reclaimed run gets a fresh physical workspace; a
  stale worker can only damage its own obsolete acquisition** (the journal
  fence protects SQLite; acquisition epochs protect the filesystem).
- Not in L0: `PreparedMerge` (L1); no `Executor.execute(workspace=…)`
  retype (M8; ADR footnote).

## 2. GitAuthority (`substrate/git/authority.py`, new)

Deterministic stdlib-subprocess plumbing. The **authority repository is
bare, protected, and only GitAuthority operates on it** — verified at init
(git ≥ 2.38 for `merge-tree --write-tree`; bare; object format recorded).
Every command runs with a pinned environment: `LC_ALL=C`, `TZ=UTC`,
`GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL` nulled,
`GIT_NO_REPLACE_OBJECTS=1`, pinned author/committer identity + dates,
`--no-gpg-sign`, `--end-of-options`, fully-qualified refs, exact OIDs after
initial resolution, messages via stdin, never a shell. Re-preparing the same
candidate onto the same base yields the same sha. A `GitEnvironment` record
(git version, object format, repository id) binds into the capability
revision.

- **Staging boundary (blocker 1):** `acquire_write(...)` creates a
  per-acquisition **staging repository** (`git init` +
  `fetch <authority> <base_sha>`) with its own working tree at
  `staging/<acquisition_id>/`; the agent may commit and mangle refs there —
  it holds zero authority refs. `import_candidate(staging, sha)` is
  authority-side: the authority **fetches the exact object** (OIDs are
  content-addressed, the commit survives import unchanged) and creates an
  authority-owned `refs/candidates/<run>/<scope>` ref. Staging is then
  disposable. The candidate crosses downstream as
  `GitRef(repository, commit, diff_against=base)` (I5).
- **Gate snapshots are exported trees**: `read_snapshot(commit)` =
  `git archive | tar -x` into a fresh dir — **no `.git` at all**, nothing
  linked to the authority — then symlink-safe chmod (files *and*
  directories, never following links) removes write bits; restored before
  cleanup. Calibrated claim (ADR-0003 style): fresh snapshot + ordinary
  writes fail + post-gate content-hash verification makes any observable
  mutation fail the check; containment of hostile same-uid code remains
  the M8 sandbox layer's job — never labeled a read-only mount.
- `prepare_merge(candidate, target_ref) -> PreparedMerge` (carries the
  full MergeSubject): `merge-tree --write-tree` (exit 1 = conflict data —
  never commit-tree'd; exit >1 = raised fault) + `commit-tree` with
  parents (expected_base, candidate).
- **`install(subject, idempotency_key)` — one git ref transaction**
  (`update-ref --stdin`: start/prepare/commit):
  `update <target_ref> <merge_commit> <expected_base>` **and**
  `create refs/constructicon/effects/<key> <merge_commit>` — both land or
  neither. The marker is the durable external receipt: crash after commit
  but before the SQLite receipt reconciles from the marker; a later force
  move of the target cannot erase the proof of install. On CAS failure,
  **re-read the ref**: genuinely moved → base-moved outcome; unchanged →
  transient lock, retry once then raise — never a receipt from an
  ambiguous exit.
- `reconcile_install(subject, key)`: marker == merge_commit → committed;
  marker exists but differs → `GitAuthorityDamaged`; no marker but target
  at merge_commit → committed (identical racing actor; create the marker);
  else None (safe to execute). Reflog stays audit-only, never correctness.
- Cleanup with CAS: candidate refs deleted via
  `update-ref -d <ref> <expected>`; a moved ref is reported, not deleted.

## 3. GateRunner (`substrate/gates/runner.py`, new)

Constructed at L4 with journal + GitAuthority + `CheckSpec{name, argv,
timeout_s}` (defaults: `python -m ruff check --no-cache .`,
`python -m pytest -q -p no:cacheprovider`; `PYTHONDONTWRITEBYTECODE=1`;
writable tmp dir outside the snapshot). `verify(candidate, target_ref, *,
run_id) -> MergeEvaluation{subject: MergeSubject | None, attestation_id:
str | None, checks, ok}`:

- Derives `manifest_hash = journal.run_manifest_hash(run_id)` itself —
  provenance is never caller-supplied.
- Conflict → `subject=None`, `checks=[merge-conflict: status="conflict"]` —
  red is data; a caller that fabricates a subject anyway is refused at the
  adapter.
- Gates run inside the **exported read-only snapshot of the merge commit**
  with process-group ownership: timeout/cancel kills the whole tree;
  output is bounded inline with a truncation marker (a content-addressed
  artifact store is future work, noted — bounded truthful detail now);
  hung/damaged/missing-executable outcomes map to their honest statuses,
  never clean success (I4).
- `check_set_hash` covers name, argv, timeout, env policy, resolved
  executable, and tool versions — the tested tree binds `pyproject.toml`,
  not which binaries ran.
- Mints via the journal from an `AttestationDraft` (§6) and returns the
  typed evaluation. Gate components are ordinary registered components
  calling this via `ctx.capability(alias)`.

## 4. MergeVerifiedEffect (`substrate/effects/git.py`, new)

Kind `"merge_verified"`, recovery `"reconcilable"`, constructed with
journal + GitAuthority.

- `execute`: load the attestation by id (absent → refuse: "a
  caller-authored claim cannot authorize a merge"). Verify
  `action == "merge"`, `attestation.subject ==
  MergeSubject.model_validate(request.subject)` — **exact typed equality
  on the complete subject** — `attestation.manifest_hash ==
  request.manifest_hash` (an attestation from an unrelated world cannot
  authorize the same subject), `attestation.ok`. Defense in depth: git
  object integrity (`merge_commit^{tree} == tested_tree`, parents ==
  (expected_base, candidate)). **All verification failures raise and leave
  no terminal receipt** — a forged proof must not poison the idempotency
  key. Then the §2 transaction: success → committed receipt
  (external_reference = installed sha); target genuinely moved →
  **rejected receipt** with `{expected_base, found_base}`.
- `reconcile`: delegates to marker-based `reconcile_install`.
- Receipt semantics calibrated: a **journaled** rejected receipt is as
  final as a journaled committed one (a failed CAS has no external side
  effect, so a crash before journaling it may truthfully re-evaluate).
  Rejected is reserved for external deterministic outcomes (base moved,
  target deleted) — never for verification failures.

## 5. Runtime: leases, boundary, admission

- **Walker**: for bindings whose descriptor declares `leased=True`
  (activation verifies the capability implements `LeasedCapability`), the
  walker acquires before invoking (fenced row keyed
  `(lease_id, acquisition_epoch)`), injects the acquired resource, and
  closes on every exit path — completed → `close(release)`; failed →
  `close(discard)`; run terminal → reap leftovers; OwnershipLost → touch
  nothing; claim/resume → `reconcile`: **checkpoint exists → reap physical
  leftovers, durable GitRefs stand; no checkpoint → discard the stale
  acquisition and re-execute from the pinned base — never adopt a dirty
  workspace as completed computation** (M2's law: uncheckpointed work may
  replay). Ordering pinned: physical op → fenced lease row → run
  transition; transitions idempotent at-target.
- **Effect boundary**: dedupe `committed` **and** `rejected` (unknown
  reconciles); supply run_id + manifest_hash into every EffectRequest;
  truthful event kinds — EffectCommitted / EffectRejected /
  EffectReconciled / EffectDeduplicated.
- **Validator + CapabilityDescriptor**: descriptor gains `leased: bool`
  and `requires_posture: Posture | None`; admission faults a
  WRITE-workspace binding under READ grants (the executor-posture check's
  analog) and compiles lease lifetime explicitly (M3: `"invocation"` only —
  the candidate ref, not the worktree, carries state across nodes;
  scope-lifetime sharing is M4).

## 6. Journal (`core/journal.py`, `substrate/journal/sqlite.py`)

- **Minting becomes literal**: `mint_attestation(run_lease, draft) ->
  Attestation` — the journal verifies the fence, derives `created_by_run`,
  assigns `created_at`, computes the content-derived id
  (`digest("attestation", 1, draft)` — timestamp excluded), inserts
  write-once. Run-less deterministic policies use an explicit
  `mint_policy_attestation(draft)` (registry promote/rollback migrate to
  these; no more caller-selected ids, no nullable-lease blur).
- `SCHEMA_VERSION = 3`; `capability_leases` table: `(lease_id,
  acquisition_epoch)` PK, run_id, binding_id, scope_json, lifetime,
  `state ∈ {active, suspended, closed, lost}`, `disposition ∈ {released,
  discarded, retained} | NULL`, resource_ref, timestamps. Fenced write-once
  `record_capability_lease`, CAS + event `transition_capability_lease`
  (idempotent at-target), `capability_leases(run_id)` read. Migration
  chain v0→v2→v3, v2→v3, fresh→v3, newer→refuse; migration tests extended
  (M1 fixture → v3; new v2 fixture).

## 7. Acceptance slice + failure tests (`tests/`)

Fixture: bare tmp authority repo holding a minuscule python package (one
module, one test), `refs/heads/main` as target. Graph: propose (writes a
scripted fix in the staged WRITE workspace, `commit_all` → import → GitRef)
→ gate (GateRunner, real ruff + pytest) → merge
(`ctx.effect("merge_verified", subject, attestation_id=…)`). Root grants
WRITE.

- **Zero ambient authority (blocker 1's test)**: from inside the leased
  workspace run `git update-ref refs/heads/main <candidate>` (and
  `branch -f`, `push`) → the staging repo may change; the authority target
  ref stays byte-identical; only the effect moves it.
- **Base moves after gates pass** → rejected receipt naming
  expected/found; no install; revalidation against the new base is a new
  subject and key. **Rejected is final**: same-subject retry returns the
  same receipt.
- **Forgery matrix** → fabricated id, failing checks, mismatched subject
  (each field), mismatched manifest_hash, wrong merge object
  (tree/parent-1/parent-2) → raised refusal, no git transition, **no
  terminal receipt** (the key is not poisoned; a valid retry can still
  commit).
- **Exact commit**: installed ref == attested `merge_commit` (the object,
  not just its tree); `installed^{tree} == tested_tree`.
- **Conflict path**: conflicting candidate → `status="conflict"` check →
  evaluation not ok → no subject, refusal via the evidence path.
- **Crash lanes with real git**: probes `effect.after_prepared_commit`
  (reconcile absent → execute exactly once) and
  `effect.before_receipt_txn` (transaction committed, SQLite receipt lost
  → **marker-ref reconcile**, exactly one install ever) — unit lane + one
  `os._exit` subprocess case reusing the M2 crash-worker pattern.
- **Two races, distinct**: same subject + same key → one physical install,
  both callers observe committed (loser reconciles the marker); different
  subjects + same expected base → exactly one committed, one rejected, the
  ref never torn.
- **Reproduce never re-installs**: same manifest_hash ⇒ same key ⇒ dedup
  (pinned deliberately — the key excludes run_id).
- **Acquisition fencing**: reclaim mid-node → fresh acquisition path; the
  stale acquisition's writes never reach the new owner's workspace; reap
  when the worktree vanished out-of-band; `FakeLeasedCapability` (I6
  double) drives every walker lease path without git.
- **READ physical**: editing and creating files in a snapshot raise
  `PermissionError`; a gate that mutates its tree fails post-gate content
  verification; gates run green without write access.
- **Gate truthfulness**: hung gate → `status="timeout"` with salvaged
  partial output; missing executable → `infrastructure_error`; never clean
  success.
- **Admission**: WRITE-incapable executor at WRITE posture → fault
  (existing law, new test); WRITE-workspace binding under READ grants →
  fault (new law).
- **Lifecycle**: discard on FAILED (staging + worktree + candidate ref
  gone, CAS-checked deletes), release on SUCCEEDED (candidate ref deleted
  iff merged, else retained and journaled), reconcile after crash.

## 8. ADR 0009 + docs

`docs/adr/0009-git-authority.md`: the staging-repository boundary (why a
linked worktree can never back an agent); the complete MergeSubject; the
install transaction with marker refs; acquisition epochs; journal-computed
attestation ids; pinned git environment; calibrated read-only and rejection
claims; invocation-lifetime-only (M4 note); workspace-param retype deferred
(M8 footnote). ARCHITECTURE milestone M3 → done at completion; README
status.

## Files

- `src/constructicon/core/effect.py` — MergeSubject, CheckResult.status,
  AttestationDraft, EffectRequest run/manifest fields.
- `src/constructicon/core/workspace.py` (new) — WorkspaceView,
  WriteWorkspace, LeasedCapability, LeaseContext, AcquiredCapability.
- `src/constructicon/core/journal.py` — draft-based minting, lease ops.
- `src/constructicon/substrate/git/{__init__,authority}.py` (new).
- `src/constructicon/substrate/gates/{__init__,runner}.py` (new).
- `src/constructicon/substrate/effects/git.py` (new).
- `src/constructicon/substrate/journal/sqlite.py` — v3 chain, lease table,
  minting, truthful effect events.
- `src/constructicon/runtime/walker.py` — lease paths, boundary changes.
- `src/constructicon/runtime/{registry,validator}.py` — descriptor fields,
  posture/lifetime admission, draft-based policy minting.
- `src/constructicon/api/system.py` — git-world assembly convenience.
- `docs/adr/0009-git-authority.md` (new); ARCHITECTURE/README updates.
- `tests/substrate/test_git_authority.py`, `tests/e2e/test_build_slice.py`,
  `tests/e2e/test_merge_effect.py`, `tests/runtime/test_leases.py` (fake
  leased capability), `tests/runtime/test_isolation.py`, migrations
  extended; existing 72 tests stay green (updated where minting/CheckResult
  signatures moved).

Reuse: identity law everywhere (subjects, lease/acquisition/attestation
ids, check-set hashes); M2's effect boundary, fault probes, FakeClock,
crash-worker pattern; `_verify_promotion_attestation`'s shape.

## Out of scope

Loops/scope-lifetime sharing (M4) · SDK (M5) · MCP (M6) · channels (M7) ·
live executors, sandbox wrappers, workspace-param retype, hostile same-uid
containment (M8) · learning (M9) · content-addressed artifact store
(future; gate output is bounded inline for now). No IR changes; additive
schema behind user_version 3.

## Verification

`uv run verify` — credential-free (bare repos + staging repos in tmp dirs;
real ruff/pytest subprocesses). Acceptance: the slice merges a gated
candidate exactly once through one git transaction; every failure test
above passes; the strongest claim is mechanically true — **the only path
from proposed code to a protected git ref is one exact, attested,
idempotent git transaction.**
