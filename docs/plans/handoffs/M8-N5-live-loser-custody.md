# M8 N5: a live loser's custody

Status: implemented with its proof. This is a prerequisite for Stage 1's
recovery claims (Astra's decision, hardline message 735, item 4).

## The seam

ADR 0018:242 requires that "cancellation/ownership loss quiesces work before
returning". The codex handle missed this.

Materialization moves the acquisition guard and the binding-store lock into
the handle (`codex.py`, `_materialize_owned`). They are released only by
`cleanup`, which only `close` calls. After ownership loss the walker
deliberately closes nothing, because disposition is the successor's (the
`OwnershipLost` and latched-loss branches of `Walker._invoke`).

So a losing process that stays alive keeps its custody. The successor's
reconciliation commits closure and then waits on that guard
(`dispose_acquisition`), until the loser's process exits. When `RunHost`
re-claims the run in the same process, that is never. Killing the loser hides
the seam rather than proving recovery.

## The fix

Local relinquishment is kept separate from durable disposition.

- **L0** (`core/workspace.py`) gains an optional `RelinquishingCapability`
  protocol with one method, `relinquish(acquisition)`. It must stop and join
  the acquisition's work and release what this process holds, writing nothing
  durable.
- **The walker** relinquishes recorded acquisitions on both loss paths, in
  one joined batch like close, and then re-raises the loss unchanged. A
  provider without the protocol keeps its legacy behaviour.
- **The codex handle** splits its cleanup into two parts:
  - **Durable:** the closure commit, in close only.
  - **Local:** join the materialization, exchange and worker tasks, then
    release the store lock and the guard. This is one shared task, so close
    and loss never release twice.

  `relinquish` runs only the local part. It never commits closure; the
  successor's reconciliation does.

## Proof

**`tests/runtime/test_ownership_loss_custody.py`.** A retaining double holds
exclusive, process-local custody exactly as the codex handle does. A
materialization that succeeds retains it; one that fails releases its own. The
loss comes mid-call, after materialization, in both forms: the handle's own
control check raises it, or the heartbeat latches it and cancels.

On `main` the loser returns holding custody, and the successor's recovery
times out on it. With the fix:
- the loser closes nothing and leaves its row `active`;
- it holds no custody once it returns;
- the successor reconciles and the run succeeds.

The existing ledger-fake loss test, whose provider has no `relinquish`, is
unchanged.

**`tests/substrate/test_codex_adapter.py`**, two tests:
- **Portable.** Relinquishment cancels the in-flight exchange and releases the
  store lock and guard, commits no closure, and refuses later execution. A
  successor then reconciles.
- **Linux, with the real `flock` guard.** The successor's reconciliation is
  first shown waiting on the live loser's guard (the control), then completes
  once the loser relinquishes.

**Mutants.** Four new mutants, all killed:
- `check_m8_native_recovery_mutations`: both walker relinquish calls.
- `check_m8_n3a_mutations`: the handle releasing custody, and the handle
  committing no closure.

Three existing anchors follow the moved code.
