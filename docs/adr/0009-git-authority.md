# 0009 — Git authority: staged workspaces, one exact install transaction

**Status:** accepted (M3) · realizes I1/I2 in git; extends ADR 0003/0008.

## Decision

The **authority repository is bare and protected**: only deterministic
substrate code (`GitAuthority`, stdlib subprocess plumbing, pinned
environment — identity, dates, locale, no system/global config, no
gpg, never a shell) touches its refs, and a deny-all `pre-receive` hook
physically refuses every push. **No agent workspace is ever a linked
worktree of the authority**: linked worktrees share `refs/*`, so an agent
inside one could `update-ref` the authority branch directly and "one
install path" would be false.

- **WRITE workspaces are staging repositories** — per-acquisition
  `git init` + fetch of the exact base. Agents may commit and mangle refs
  there; they hold zero authority refs. `commit_all` imports the exact
  candidate object authority-side (OIDs are content-addressed) under an
  authority-owned `refs/candidates/…` ref; candidates cross between nodes
  as `GitRef` (I5). Candidate refs are retained durable evidence after a
  clean release (they anchor the merge commit's second parent for resume
  and audit); they are CAS-deleted when an invocation's uncheckpointed
  work is discarded. Candidate-ref GC beyond that is future work.
- **Read snapshots are exported trees** (`git archive` → tarfile,
  symlink-safe write-bit removal on files and directories). Calibrated
  claim: a fresh snapshot + failing ordinary writes + post-gate
  content-hash verification make any observable mutation fail the check.
  Permission bits do not bind privileged (root) or hostile same-uid code —
  that containment is the M8 sandbox layer; this is not a read-only mount.
- **One complete typed subject.** `MergeSubject{repository, target_ref,
  candidate, expected_base, merge_commit, tested_tree}` (target refs always
  fully qualified; arbitrary targets first-class) is used identically by
  the prepared merge, the attestation, the effect request, idempotency,
  reconciliation, and receipts. `merge_verified` verifies exact subject
  equality, world binding (`attestation.manifest_hash` equals the invoking
  manifest), `attestation.ok`, and — defense in depth — git object
  integrity (`merge_commit^{tree} == tested_tree`, parents ==
  (expected_base, candidate)).
- **One git ref transaction per install** (`update-ref --stdin`): the
  target CAS-moves from `expected_base` to `merge_commit` AND a marker ref
  `refs/constructicon/effects/<idempotency-key>` is created — both or
  neither. The marker is the durable external receipt: reconciliation
  reads it after any crash; a later force move of the target cannot erase
  the proof of install. A failed transaction is disambiguated by
  re-reading the ref — only a genuine move becomes a `rejected` receipt;
  an unchanged ref is transient lock contention (retry once, then raise).
- **Minting is literal** (I2): callers author `AttestationDraft`s; the
  journal computes the content-derived id (timestamps excluded), derives
  `created_by_run` from the fenced run lease (`mint_attestation`), or
  takes the one explicit lease-free path for deterministic run-less
  policies (`mint_policy_attestation`). Verification failures at the
  effect **raise and leave no receipt** — a forged proof cannot poison an
  idempotency key. `rejected` is reserved for external deterministic
  outcomes; a journaled rejected receipt is as final as a committed one.
- **Physical acquisitions are epoch-fenced.** `lease_id` is computed from
  (run, scope, binding); `acquisition_id` from (lease_id, ownership
  epoch); staging paths key on the acquisition. A reclaimed run gets a
  fresh physical workspace — a stale worker can only damage its own
  obsolete acquisition (the journal fence protects SQLite; acquisition
  epochs protect the filesystem). Reconcile on reclaim: checkpointed
  invocation → reap leftovers, durable refs stand; uncheckpointed →
  discard and replay from the pinned base — never adopt a dirty workspace
  as completed computation. M3 leases are invocation-lifetime only; the
  candidate ref, not the worktree, carries state across nodes and loop
  iterations. M4 confirmed that invocation lifetime is sufficient:
  `reset_to(GitRef)` reconstructs each iteration from durable data, leaving
  scope lifetime with no consumer (I6).
- Gates are ordinary registered components calling the `GateRunner`
  capability; the runner (bound per node with the walker-supplied lease
  context) runs real checks inside the read-only snapshot of the prepared
  merge commit, maps timeouts/missing tools to honest `CheckResult`
  statuses (never clean success), binds the resolved tool versions into
  `check_set_hash`, and mints the attestation. `candidate == base` is
  reported as `already-integrated` — a reproduced run over an installed
  world says so truthfully instead of double-installing.

## Rejected

- Linked worktrees for agents (shared refs = shared authority).
- Reflog-based reconciliation (an audit facility, not guaranteed to exist
  or persist; the marker ref is correctness, the reflog stays audit).
- `merge_commit` verified only by tree/parent integrity (multiple commit
  objects can share both; the subject binds the exact object).
- A `rejected` receipt for verification failures (poisonable keys).
- Retyping `Executor.execute(workspace=…)` now — no M3 consumer;
  it lands with M8's live executors.

## Consequences

The strongest claim is mechanically true and tested: **the only path from
proposed code to a protected git ref is one exact, attested, idempotent git
transaction.** Requires git ≥ 2.38 (`merge-tree --write-tree`), verified at
authority construction.
