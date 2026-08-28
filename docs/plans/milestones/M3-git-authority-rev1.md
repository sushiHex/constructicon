# M3 — git authority (rev 1, red-team fixes incorporated)

## Context

M1 (vertical slice) and M2 (crash & resume hardening) are merged; the
architecture is frozen. M3 is the authority layer named in the frozen
milestone list: **read-only snapshots, WRITE worktree leases, Pytest/Ruff
gates, exact-merge-tree attestations, discard-on-failure** — I1 made real:
effects belong to deterministic code operating on git and the journal; LLMs
propose, code validates, executes, disposes.

```
Lease worktree → Propose (commit) → Prepare exact merge → Gates (read-only)
      → Journal-minted Attestation → merge_verified(attestation_id)
      → CAS install or truthful refusal → discard / release
```

**Acceptance criterion:** a run can lease a WRITE worktree branched from a
pinned base, commit a candidate, have deterministic gates (real Ruff + real
Pytest subprocesses) run against the prepared merge commit of candidate into
the current base inside a physically read-only snapshot, mint a journal
Attestation binding `GitProofSubject{repository, commit, base, tested_tree}`,
and install **that exact commit** through the effect boundary —
`merge_verified(attestation_id)` — which refuses with a truthful `rejected`
receipt when the base moved, reconciles instead of re-executing after any
crash, and never installs on a forged, absent, mismatched, or failing
attestation. Worktrees and candidate branches are discarded on terminal
failure, released on success, reconciled (restored or reaped) after a crash;
`uv run verify` stays credential-free (local bare repos in tmp dirs).

Pinned assertions: one attestation minter (the journal) · one install path
(update-ref CAS) · installed commit's tree byte-equals the tested tree · a
rejected receipt is as final as a committed one · gates cannot go green by
mutating what they test · the walker knows leases, never git.

## 1. Core contracts (`core/workspace.py`, new — deliberately small)

- `WorkspaceView` protocol: `path: str`, `git_ref() -> GitRef` — what any
  node or gate holds. `WriteWorkspace(WorkspaceView)` adds
  `commit_all(message: str) -> GitSha`. I6 pair: the read snapshot and the
  write worktree are the two real implementations.
- `LeasedCapability` protocol (runtime_checkable): `acquire(run_id, scope)
  -> tuple[object, str]` (live resource + `resource_ref`), `release(ref)`,
  `discard(ref)`, `suspend(ref)`, `reconcile(run_id) -> report`. The walker
  owns every `CapabilityLease` transition on every exit path by calling
  these five verbs — it never learns what a worktree is. I6 double:
  `FakeLeasedCapability` in tests exercises the same walker paths.
- **Not** in L0: `PreparedMerge` (L1, substrate/git); no retype of
  `Executor.execute(workspace=…)` — that lands with M8's live executors
  (footnote in ADR 0009). `CapabilityLease` (already in core/manifest.py)
  gets its first producer; `lease_id` is **computed**:
  `digest("capability-lease", 1, {run_id, scope, binding})` — write-once
  re-acquire after a mid-node crash is idempotent, never a second row.

## 2. GitAuthority (`substrate/git/authority.py`, new)

Deterministic stdlib-subprocess plumbing over one **bare** authority
repository plus a workspaces root; verifies at init: git ≥ 2.38
(`merge-tree --write-tree`), repo is bare (an update-ref under a live
checkout silently corrupts it). Every commit-creating op pins
`GIT_AUTHOR_*`/`GIT_COMMITTER_*` (fixed identity + fixed date): re-preparing
the same candidate onto the same base yields the same sha — subject
stability across crash/re-run, and CI needs no git identity.

- `read_snapshot(commit) -> ReadSnapshot` — detached worktree, then chmod
  write bits off **files and directories** (blocks edits and creation).
  Honest threat model (ADR 0003 style): this stops accidental writes, not
  hostile same-uid code; the boundary remains admission (ADR 0008).
- `lease_write_worktree(run_id, scope, base_branch) -> WriteWorkspace` —
  resolves base to an exact sha (pinned), `git worktree add -b
  candidate/<run>/<scope>` at a deterministic path
  `<root>/<run_id>/<scope>` so post-crash reconcile can find it. M3 leases
  are **invocation-lifetime only**: the worktree closes with the node; the
  candidate **branch** is what carries the commit across nodes (I5: code
  crosses as `GitRef`). Scope-lifetime sharing is M4 build-loop machinery.
- `prepare_merge(candidate, base_branch) -> PreparedMerge{repository,
  candidate, base, merge_commit, tested_tree}` — `merge-tree --write-tree`
  (exit 1 = conflict data, never committed; exit >1 = raised fault) +
  `commit-tree` with parents (base, candidate).
- `install_verified(subject…) -> GitSha` — `git update-ref
  refs/heads/<base> <merge_commit> <expected_base>`: git's own CAS. On
  nonzero exit, **re-read the ref**: genuinely moved → base-moved outcome;
  unchanged → transient lock, retry once then raise. Never a receipt from
  an ambiguous exit.
- `reconcile_install(subject) -> committed | absent | superseded` — base at
  or containing merge_commit → committed; otherwise consult the base ref's
  **reflog**: merge_commit found-then-moved → committed (observed_state
  notes supersession); truly absent → safe to execute.
- Branch/worktree closure: FAILED/CANCELLED → discard branch + leftover
  worktree; SUCCEEDED → release (delete worktree; delete branch iff merged
  into base, else retain and say so in the run's events).

## 3. GateRunner (`substrate/gates/runner.py`, new)

Constructed at L4 with journal + GitAuthority + `CheckSpec{name, argv,
timeout_s}` tuple (default: `ruff check .`, `pytest -q`).
`verify(candidate, base_branch, *, run_id) -> (attestation_id, checks)`:

- Derives `manifest_hash = journal.run_manifest_hash(run_id)` itself —
  never caller-supplied provenance (I2/I4).
- Prepares the merge; conflict → `CheckResult(ok=False)` — a red check is
  data, not an error.
- **Gates run inside `read_snapshot(merge_commit)`** — the read-only
  snapshot's real consumer: a gate cannot go green by mutating the tree.
  Timeout/damaged output → `ok=False` with salvaged partial detail (I4),
  never clean success.
- Mints `Attestation{action="merge", subject=GitProofSubject{repository,
  commit=candidate, base, tested_tree}, checks, check_set_hash=digest over
  specs, manifest_hash, created_by_run=run_id}` into the journal; returns
  the id. Nodes never construct attestations; gate components are ordinary
  registered components calling this via `ctx.capability(alias)`.

## 4. MergeVerifiedEffect (`substrate/effects/git.py`, new)

`EffectAdapter`, kind `"merge_verified"`, recovery `"reconcilable"`,
constructed with journal + GitAuthority. Subject dict pinned:
`{repository, commit, base, merge_commit, tested_tree}` (base in the
subject ⇒ revalidation against a moved base is a **new** idempotency key).

- `execute`: `attestation_id` required → `journal.load_attestation`; absent
  → refuse ("a caller-authored claim cannot authorize a merge" — mirror of
  promotion). Verify action, subject type, field-by-field subject match,
  `attestation.ok`. **The attestation cannot bind `merge_commit`
  (GitProofSubject has no such field) — verify it via git object
  integrity instead**: `merge_commit^{tree} == tested_tree`,
  `merge_commit^1 == base`, `merge_commit^2 == candidate`; any mismatch is
  a raised refusal. Then CAS install → committed receipt
  (external_reference = installed sha); base genuinely moved → **rejected
  receipt** with `{expected_base, found_base}` — an external CAS outcome
  is data, exactly like `store_promotion`.
- `reconcile`: delegates to `reconcile_install` (reflog-aware) → committed
  receipt or None.

## 5. Runtime: leases through the walker, admission knows postures

- **Walker** (`runtime/walker.py`): for capability bindings whose
  descriptor declares `leased=True` (activation verifies the object
  actually implements `LeasedCapability`), the walker acquires before
  invoking the node, records the fenced `capability_leases` row, injects
  the acquired resource as the capability, and closes on every exit path —
  node completed → release; node failed → discard; run terminal → reap
  leftovers; OwnershipLost → touch nothing; claim/resume →
  `reconcile(run_id)` restores or reaps. Ordering pinned: physical op →
  fenced lease-row transition → run transition; lease transitions are
  idempotent at-target (mirror of `record_completion`), so crash between
  steps re-runs closure safely. One more boundary change: a `rejected`
  receipt is **final** — the effect boundary dedupes and returns it just
  like committed (today only committed short-circuits; a same-key retry
  with a different `found_base` would otherwise hit the write-once law as
  `JournalDamaged`).
- **Validator** (`runtime/validator.py`) + `CapabilityDescriptor`
  (`runtime/registry.py`): descriptor gains `leased: bool = False` and
  `requires_posture: Posture | None = None`; admission faults a
  WRITE-workspace binding under READ-postured grants (isolation is
  admission logic — the analog of the executor-posture check), and
  compiles lease lifetime explicitly (M3: assert `"invocation"`).

## 6. Journal (`core/journal.py`, `substrate/journal/sqlite.py`)

- `SCHEMA_VERSION = 3`; additive `capability_leases` table {lease_id PK,
  run_id, binding_id, scope_json, lifetime, state, resource_ref,
  created_at, updated_at}. Migration dispatch becomes a chain: v0→v2→v3,
  v2→v3, fresh→v3, newer→refuse; `tests/migrations` extended (M1 fixture
  now migrates to v3; plus a v2-shaped fixture).
- Fenced ops: `record_capability_lease(run_lease, cap_lease)` (write-once
  on computed lease_id), `transition_capability_lease(run_lease, lease_id,
  *, expected, target)` (CAS + event, one txn, idempotent at-target),
  `capability_leases(run_id)` read. Lease state lives here and only here —
  never in checkpoints, never a second store.

## 7. Acceptance slice + failure tests (`tests/`)

Fixture: bare tmp repo containing a minuscule python package (one module,
one test) with `main` as base. Graph: propose (component impl writes a
scripted fix into the WRITE worktree, `commit_all` → emits `GitRef`) →
gate (GateRunner: real ruff + pytest subprocesses) → merge node
(`ctx.effect("merge_verified", subject, attestation_id=…)`). Root grants
WRITE (narrowing law unchanged).

Failure tests (the frozen table's M3 rows plus red-team additions):
- **Base moves after gates pass** → rejected receipt naming
  expected/found; no install; revalidate-on-new-base is a new key.
- **Rejected is final**: resume/retry of the same subject returns the same
  rejected receipt — no write-once conflict, no re-CAS.
- **Forgery**: fabricated attestation_id / failing checks / mismatched
  subject / wrong merge_commit (tree, parent-1, parent-2 each) → refused.
- **Exact tree**: `installed^{tree} == tested_tree` byte-exact.
- **Conflict path**: conflicting candidate → red merge-conflict check →
  attestation not ok → merge refused via the evidence path.
- **Crash lanes with real git**: probes `effect.after_prepared_commit`
  (reconcile absent → execute exactly once) and
  `effect.before_receipt_txn` (installed, receipt lost → reconcile via
  reflog, exactly one merge commit ever) — unit lane + one subprocess
  `os._exit` acceptance case reusing the M2 crash-worker pattern.
- **Concurrent install race**: two workers CAS the same base → exactly one
  committed, one rejected, ref never torn.
- **Reproduce never re-installs**: same manifest_hash ⇒ same idempotency
  key ⇒ dedup on the committed receipt (pinned deliberately — the key
  excludes run_id).
- **READ physical**: editing an existing file AND creating a new file in a
  snapshot raise `PermissionError`; gates run green without write access.
- **Admission**: WRITE posture with an executor that can't enforce
  `workspace_only` → fault (existing law, new test); WRITE-workspace
  binding under READ grants → fault (new law).
- **Gate salvage**: hung/killed gate subprocess → `ok=False` with partial
  output, never clean success (I4).
- **Lease lifecycle**: discard on FAILED (worktree + branch gone), release
  on SUCCEEDED (branch deleted iff merged), reconcile after crash restores
  or — when the worktree vanished out-of-band — reaps; `FakeLeasedCapability`
  drives the walker's generic paths without git.

## 8. ADR 0009 + docs

`docs/adr/0009-git-authority.md`: bare authority repo + worktree leases;
prepared-merge via merge-tree with pinned commit identity; install =
update-ref CAS with re-read disambiguation; merge_commit verified by object
integrity because GitProofSubject binds {commit, base, tested_tree};
rejected receipts are final; discard/retain policy per lifecycle state;
invocation-lifetime-only in M3 (scope arrives with M4);
`Executor.execute(workspace=…)` retype deferred to M8 (footnote).
`docs/ARCHITECTURE.md` milestone M3 → done (at completion); README status.

## Files

- `src/constructicon/core/workspace.py` (new) — WorkspaceView,
  WriteWorkspace, LeasedCapability.
- `src/constructicon/core/journal.py` — capability-lease ops.
- `src/constructicon/substrate/git/{__init__,authority}.py` (new).
- `src/constructicon/substrate/gates/{__init__,runner}.py` (new).
- `src/constructicon/substrate/effects/git.py` (new).
- `src/constructicon/substrate/journal/sqlite.py` — v3 chain, lease table,
  fenced lease ops.
- `src/constructicon/runtime/walker.py` — lease acquire/close paths;
  rejected-receipt dedupe (reuse `_effect_boundary`).
- `src/constructicon/runtime/{registry,validator}.py` — descriptor fields,
  posture/lifetime admission.
- `src/constructicon/api/system.py` — assembly convenience for the git
  world (capabilities/catalog/effects splice).
- `docs/adr/0009-git-authority.md` (new); ARCHITECTURE/README updates.
- `tests/substrate/test_git_authority.py`, `tests/e2e/test_build_slice.py`,
  `tests/e2e/test_merge_effect.py`, `tests/runtime/test_leases.py` (fake
  leased capability), `tests/runtime/test_isolation.py`, migrations
  extended; existing 72 tests stay green.

Reuse: identity law for lease ids/check-set hashes; the M2 effect boundary,
fault probes, crash-worker pattern, FakeClock; `_verify_promotion_attestation`'s
shape for merge verification; `uv run verify` remains the single gate.

## Out of scope

Loops/scope-lifetime sharing (M4) · SDK/describe-rich (M5) · MCP (M6) ·
channels (M7) · live executors + sandbox wrappers and the workspace retype
(M8) · learning (M9). No IR changes; additive schema only behind
user_version 3.

## Verification

`uv run verify` — all lanes credential-free (bare repos in tmp dirs, real
ruff/pytest as subprocesses of the test run). Acceptance: the slice merges a
gated candidate exactly once; every failure test above passes; a second
`Constructicon` over the same files reconciles a crashed run's leases and
never doubles an install; M1- and M2-shaped databases migrate to v3 losing
nothing.
