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
- **The walker** relinquishes recorded acquisitions wherever it finds a loss:
  - the two loss paths in `_invoke` (an observed loss, and a latched loss that
    a cancellation delivers);
  - ordinary close, when a fenced row transition finds the run lost. The
    siblings not yet closed are then relinquished, not closed.

  The hand-off itself must not fail differently from the loss it serves:
  - every acquisition is attempted even after one fails;
  - the batch is joined through cancellation without surfacing it, so the
    loss stays primary, as on the latched path;
  - failures become the loss's `__cause__`, the precedent being
    `raise lost from cleanup` in `_acquire_invocation_capability`.

  With nothing to relinquish there is no `await` at all, so a provider
  without the protocol keeps its legacy loss path exactly.
- **The codex handle** splits its cleanup into two parts:
  - **Durable:** the closure commit, in close only.
  - **Local:** join the materialization, exchange and worker tasks, then
    release the store lock and the guard. This is one shared task, so close
    and loss never release twice.

  `relinquish` runs only the local part. It never commits closure; the
  successor's reconciliation does. Its release failures surface even when
  its own caller is cancelled while joining.

## Proof

Every new test below was first shown failing against the code it guards.

**`tests/runtime/test_ownership_loss_custody.py`.** A retaining double holds
exclusive, process-local custody exactly as the codex handle does: a
materialization that succeeds retains it, and one that fails releases its own.
- **The seam, on both paths.** The loss arrives mid-call, after
  materialization. Either the handle's own control check raises it, or the
  heartbeat latches it (observed affirmatively) and a shutdown cancellation
  delivers it. On `main` the loser returns holding custody, and the
  successor's recovery times out. With the fix, the loser closes nothing,
  leaves its row `active` and holds nothing, and the successor's recovery
  succeeds.
- **One failed relinquishment.** The failing sibling does not strand the
  other. The loss stays primary, with the failure as its `__cause__`.
- **A cancellation during relinquishment.** The loss stays primary and the
  custody is released.
- **A loss first found by close's fenced row transition.** The sibling not
  yet closed is relinquished, not closed, and both rows stay `active` for the
  successor.

The existing ledger-fake loss test, whose provider has no `relinquish`, is
unchanged.

**`tests/substrate/test_codex_adapter.py`.**
- **Portable.** Relinquishment cancels the in-flight exchange and releases the
  store lock and guard. It commits no closure and refuses later execution, and
  a successor then reconciles.
- **The release's failures** surface even when the relinquishing caller is
  cancelled.
- **Linux, with the real `flock`.** The control is affirmative contention, not
  elapsed time. The successor has committed closure, and a non-blocking
  `flock` on the guard is refused while the live loser holds it. The
  successor's reconciliation completes once the loser relinquishes.

**Mutants.** Nine new or re-anchored mutants, all killed:
- `check_m8_native_recovery_mutations`: the observed-loss and latched-loss
  relinquish calls, per-acquisition failure collection, cancellation
  absorption, and close-path relinquishment.
- `check_m8_n3a_mutations`: the handle releasing custody, committing no
  closure, and surfacing failures through a cancelled caller.

Two existing anchors (n2 close, n3a cleanup join) follow the moved code.
