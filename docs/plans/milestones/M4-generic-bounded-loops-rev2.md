# M4 — generic bounded loops (rev 2, red-team fixes incorporated)

## Context

M1–M3 are merged. M4 executes the third and last IR construct: **generic
bounded loops with iteration identities and PARKED reasons**. The frozen
sentence, verbatim (core/graph.py):

> a loop executes its body at least once, threads declared feedback outputs
> into the next iteration, reads `continue_from` after each completed
> iteration, exports the final completed iteration's non-control outputs,
> and parks with `policy_exhausted` when `max_iterations` is reached while
> continuation remains true.

Everything compiles at admission (the walker decides nothing; feedback and
continuation are sealed manifest data); iteration identity rides the
existing `ExecutionPath.iterations` frames — checkpoints, events, effect
idempotency keys, and `invocation_id` are already frame-aware. M4 also fixes
two pre-existing iteration-blind seams (lease identity and stale-lease
reconcile) and repairs a reproduce-after-upgrade break the red-team found.

Rev 2 adopts the red-team verdict: a **bool-only, admission-typed
continuation** (a Mapping-sniffing walker would be the kernel learning what
a gate is); **park decided at graph closure** like every other terminal
status; **manifest-carried loop membership** (the walker re-derives no
structure); the body compiled under a **synthetic `body` scope segment**;
and two hard cuts — **no nested loops** (admission faults; frames keep the
addressing ready) and **no scope-lifetime leases**: the red-team's own
alternative shrinks further — a `reset_to(commit)` on the write workspace
lets the repair loop thread candidates purely through the data plane
(feedback carries the `GitRef`; the ref, not the worktree, carries state —
exactly ADR 0009's principle), leaving scope lifetime with zero consumers,
and I6 forbids abstractions without one. "PARKED resources are retained"
holds trivially: invocation leases close per node, so nothing is live at
park.

**Acceptance criterion:** a loop node admits into a sealed manifest carrying
its compiled boundary bindings, feedback bindings, continuation source, and
member scopes; executes its body at least once inside the walker's one pass;
threads feedback; stops the iteration after a completed iteration whose
boolean continuation is False — including on the final allowed iteration —
and exports that iteration's non-control outputs to downstream consumers;
parks through graph closure with `policy_exhausted` (siblings finish;
dependents report BLOCKED-on-PARKED) when the last allowed iteration still
wants to continue; every iteration has one stable `ExecutionPath`, so
checkpoints restore per iteration on resume, per-iteration effects are
idempotent, and per-iteration workspace leases never collide; a resumed
exhausted run re-parks convergently without re-executing restored work; a
git repair loop turns a red candidate green across iterations and installs
exactly once; M3 databases migrate (v3→v4) and M3-stored runs still resume
AND reproduce.

Pinned assertions: one scheduler (the walker's pass) · one boolean
continuation type, checked at admission · park is a closure decision · one
`ExecutionPath` per iteration everywhere · exports are the final completed
iteration's non-control outputs · checkpoints are truth, refs are evidence ·
no structure derived at runtime.

## 1. Core contracts

- `core/graph.py` — unchanged (the IR is frozen).
- `core/manifest.py`: `MANIFEST_SCHEMA_VERSION = 2`. New frozen
  `LoopResolution{scope: ScopePath (the loop node), body_scope: ScopePath
  (= scope.child("body") — loop and body scopes permanently distinct),
  max_iterations: int, continue_source: PortAddress,
  initial_bindings: tuple[ResolvedPortBinding, ...] (destination =
  GraphInputAddress(body_scope, port), sources = outer addresses),
  feedback_bindings: tuple[ResolvedPortBinding, ...] (same destinations,
  single body-output source each), members: tuple[ScopePath, ...] (compiled
  member instance scopes — the walker only obeys)}`. `ExecutionManifest`
  gains `resolved_loops: tuple[LoopResolution, ...] = ()` (additive; stored
  v1 manifests load with the default).
- `core/manifest.py`: `CONTINUE_TYPE = "constructicon/continue"` — the one
  nominal control type. A `continue_from` port must have this `type_id` and
  cardinality `"one"`; its payload must be exactly `bool` at runtime.
- `core/manifest.py`: `CapabilityLease.scope: ScopePath` →
  `path: ExecutionPath` (iteration-aware lease rows).
- `core/workspace.py`: `lease_id_for(run_id, path: ExecutionPath,
  binding_id)` (digest schema_version bumped to 2 so the identity change is
  explicit); `WriteWorkspace` protocol gains
  `reset_to(commit: GitSha) -> None`.
- `core/run.py`: unchanged (`ParkedReason.policy_exhausted`,
  `InvocationStatus.PARKED` get their first producers).
- Walker `RunResult` gains `parked: ParkedReason | None = None` and
  `parked_detail: str | None = None` (the loop path and iteration count).

## 2. Validator: compile the loop (replace the M4 refusal)

`_compile_node`'s Loop branch becomes `_compile_loop`:

- **Nested loops refused**: any `Loop` encountered while compiling a loop
  body faults ("nested Loop arrives with a later milestone") — frames keep
  the addressing ready; single-frame paths everywhere in M4.
- Body (Ref via the snapshot, or inline Graph) compiles under
  `body_scope = instance_scope.child("body")` with input_sources =
  **loop-boundary addresses** `GraphInputAddress(body_scope, port)` — inner
  bindings reference only boundary + inner addresses (uniform for atomic
  and composite bodies, reusing the composite retagging pattern).
- Boundary ports bind to the outer pool via the existing magnetic rules
  **including explicit `Connection.map` overrides** (ambiguity at a loop
  boundary stays repairable) → `initial_bindings`. A feedback port with no
  outer source gets a loop-specific fault ("feedback port X needs an
  initial value at the outer level").
- Feedback validation: every key a declared body input, every value a
  declared body output, `type_id` match per pair, and **cardinality "one"**
  on both the destination and `continue_from` (a `many` feedback port would
  silently change cardinality between iterations). `continue_from` must
  name a declared body output of type `CONTINUE_TYPE`; itemized faults name
  the repairs.
- Exports = body outputs **minus** the control port (frozen "non-control").
  A body whose only output is the control port is a legal zero-export sink.
  The control value never enters the outer pool (a bare bool cannot
  magnetically leak). The decision-as-data idiom (declare a separate report
  output) is documented in ADR 0010, never a kernel change.
- Feedback edges live only in `LoopResolution` — the "cycle outside Loop"
  guard is untouched. `world_hash` unchanged in shape; the manifest hash
  body takes `"schema_version": MANIFEST_SCHEMA_VERSION` (no more hardcoded
  1) and includes `resolved_loops` — stated consequence: new admissions of
  identical loop-free graphs get new manifest hashes; old runs resume under
  their stored hashes.

## 3. Walker: units and the iteration pass

- The flat instance pass becomes a pass over **units**: atomic instances
  not inside any loop, plus one unit per `LoopResolution` (membership from
  `manifest.resolved_loops[].members` — never re-derived). `_ordered`
  generalizes to unit granularity; a loop unit's producers come from its
  `initial_bindings` sources.
- **Loop unit execution** (inside the same pass — no second scheduler):
  ```
  for index in range(max_iterations):
      check lost + cancel_requested          # inside the loop, both
      frames = (IterationFrame(loop=scope, index),)
      iteration values seeded at boundary keys:
          index 0            -> initial_bindings (outer values)
          index > 0 feedback -> previous iteration's value at the source
          index > 0 other    -> outer values (loop-invariant)
      run members topologically with iteration-stamped ExecutionPaths
          (checkpoint restore, effects, leases all frame-keyed already);
          a member failure -> downstream members report NodeBlocked with
          iteration paths; the unit is FAILED
      decision = value at continue_source    # after a COMPLETED iteration
      if not isinstance(decision, bool): ContractViolation naming the port
      if decision is False: publish exports at static addresses; COMPLETED
  else:  # all iterations completed and the last decision was still True
      unit PARKED (policy_exhausted)
  ```
  The exhaustion ruling is explicit: **a False decision on the final
  allowed iteration completes normally** — only "reached while continuation
  remains true" parks.
- **Park goes through closure**, symmetric with failure: a parked unit
  publishes nothing; dependents report BLOCKED with producer status
  `InvocationStatus.PARKED`; siblings finish. Closure precedence: any
  failure → FAILED (parked detail in the payload); else any parked →
  `transition_run(RUNNING→PARKED, "RunParked", payload {reason:
  policy_exhausted, loop, iterations})` and
  `RunResult(status=PARKED, parked=…)`; else SUCCEEDED.
- Resume: the existing table already claims PARKED; re-walk restores
  completed iterations per frame-stamped checkpoint, the decision replay is
  trivially version-stable (bool), and a still-exhausted run re-parks
  convergently (one new RunParked event, nothing re-executed).
- `_materialize` learns loops: final iteration = smallest index whose
  continuation checkpoint is False; exports read from that iteration's
  checkpoints.
- `_reconcile_stale_leases` uses `row.path` directly — fixing its
  iteration-blind checkpoint lookup (a loop-body invocation's checkpoint
  now found at the frame-stamped path).

## 4. Git across iterations: the data plane, not shared worktrees

- `StagedWriteWorkspace.reset_to(commit)`: authority-side fetch of the
  exact commit into staging + hard reset — deterministic, staging-local.
  The repair loop's proposer receives the previous candidate as feedback
  **data** (`GitRef`) and resets its fresh per-iteration staging onto it;
  `import_candidate` stays **write-once** per acquisition (per-iteration
  candidate refs — lease ids now carry frames, so nothing collides).
  Checkpoints remain truth; refs remain evidence; crash/park resume seeds
  from restored checkpoint data with zero ref archaeology. No CAS-advance,
  no cross-epoch ref chains, no scope-lifetime machinery.

## 5. Journal + migration

- `SCHEMA_VERSION = 4`; `_migrate_m3_to_m4` rewrites `capability_leases.
  scope_json` rows from ScopePath to ExecutionPath shape
  (`{"segments": …}` → `{"scope": {"segments": …}, "iterations": []}`);
  column name kept (a rename is a table rebuild for nothing). Pre-M4 rows
  keep their old lease ids and are closed only via row-driven reconcile —
  stated, tested. Migration is one-way for old binaries (existing newer-
  version refusal) — stated.
- **Reproduce-after-upgrade fix**: `create_run`'s manifest write-once check
  compares **parsed manifests**, not bytes (a v1-stored JSON re-serialized
  by the v2 model differs in bytes while identical in meaning); byte
  equality remains the fast path. Tested with a real M3-stored manifest
  fixture driven through `reproduce`.
- `RunParked` is an ordinary fenced transition + event (no new columns).

## 6. Tests

- **Validator**: loop compiles into `LoopResolution` (boundary bindings,
  members, body under `…/body`); faults for feedback type mismatch, unknown
  feedback/continue ports, non-`CONTINUE_TYPE` or non-"one" continuation,
  `many` feedback destination, missing feedback seed (loop-specific
  message), nested Loop; explicit map override at a loop boundary; replaces
  `test_loops_are_refused_until_m4`.
- **Fake-world refine loop** (a counter-to-target body): executes at least
  once; threads feedback; exact iteration count; False-on-final-iteration
  completes (never parks); exports are the final iteration's non-control
  outputs; iteration-stamped events/checkpoints (`…[2]` renders);
  per-iteration effect keys distinct, replay dedups.
- **Crash lanes**: probe mid-loop (`completion.after_commit` on iteration
  1's member) → resume restores iterations 0–1, executes 2, finishes; the
  walker's `lost` check inside the loop (fenced-out worker stops
  mid-iteration); one `os._exit` subprocess case resuming a mid-loop crash.
- **Parking**: exhaustion → RunParked{policy_exhausted} through closure,
  siblings completed, dependents BLOCKED-on-PARKED with complete reports,
  `RunResult.parked`; resume re-parks convergently (restored iterations,
  no re-execution, exactly one new RunParked); parked runs project.
- **Precedence**: loop parks while a sibling branch fails → FAILED with
  parked detail in the payload.
- **Cancel** between iterations → CANCELLED.
- **Git repair loop e2e**: BROKEN_FIX → gate red → decide(continue=True) →
  feedback (checks + candidate GitRef) → propose `reset_to(previous)` +
  GOOD_FIX → gate green → decide False → merge node installs exactly once;
  candidate chain: iteration 1's commit has iteration 0's as its parent;
  park path: a never-healing proposer exhausts → PARKED, nothing installed,
  authority target untouched.
- **Leases**: per-iteration lease rows (frame-distinct ids) via
  `FakeLeasedCapability` inside a loop; stale-lease reconcile at a
  frame-stamped path takes the release branch when that iteration
  checkpointed (the fixed M3 seam).
- **Migrations**: v3→v4 row rewrite; M1→v4 chain still green; the
  reproduce-after-upgrade manifest fixture.
- Existing 102 tests stay green (updated only where CapabilityLease/
  lease_id_for signatures moved).

## 7. ADR 0010 + docs

`docs/adr/0010-loop-execution.md`: bool-only admission-typed continuation;
park as a closure decision; manifest-carried membership; the `body` scope
segment; exports-minus-control with the decision-as-data idiom; nested
loops deferred (frames ready); scope-lifetime leases deferred with the
reasoning (the candidate `GitRef` through feedback is the state carrier —
ADR 0009's principle — leaving scope lifetime consumer-less; I6);
`reset_to` semantics; migration/compat notes ((f) items). ARCHITECTURE
milestone M4 → done at completion + a loop row in the failure-test table;
README status.

## Files

- `src/constructicon/core/manifest.py` — LoopResolution, resolved_loops,
  CONTINUE_TYPE, CapabilityLease.path, MANIFEST_SCHEMA_VERSION 2.
- `src/constructicon/core/workspace.py` — lease_id_for(path), reset_to.
- `src/constructicon/runtime/validator.py` — `_compile_loop` + boundary
  binding + hash-body version fix.
- `src/constructicon/runtime/walker.py` — unit pass, iteration executor,
  park-at-closure, RunResult.parked, materialize/reconcile fixes.
- `src/constructicon/substrate/git/authority.py` — reset_to; acquire uses
  context.path.
- `src/constructicon/substrate/gates/runner.py` — acquire uses context.path.
- `src/constructicon/substrate/journal/sqlite.py` — v4 migration, parsed-
  manifest write-once, lease row path shape.
- `docs/adr/0010-loop-execution.md` (new); ARCHITECTURE/README updates.
- `tests/runtime/test_loop_validator.py`, `tests/e2e/test_loop_slice.py`,
  `tests/e2e/test_repair_loop.py`, loop cases in `test_leases.py` +
  crash-worker lane, `tests/migrations/test_m3_to_m4.py`; fixtures extend
  `tests/conftest.py` / `tests/gitworld.py`.

Reuse: `_bind_port`/`_bind_node_inputs`/retagging (validator), the M2/M3
walker machinery (checkpoint restore, effect boundary, lease verbs, fault
probes, FakeClock, crash workers), `_path_key`/`idempotency_key`/
`invocation_id` (already frame-aware).

## Out of scope

Nested loops · scope-lifetime leases (deferred with reasoning, ADR 0010) ·
SDK loop sugar (M5) · MCP (M6) · channels/approval-driven unparking (M7) ·
live executors (M8) · learning loops (M9) · budget accounting beyond
max_iterations (`BudgetExhausted` stays declared). No IR changes; additive
manifest field + one journal migration.

## Verification

`uv run verify` — all lanes credential-free. Acceptance: the frozen loop
sentence holds clause by clause under tests; the repair loop turns red to
green and installs exactly once; exhaustion parks through closure and
re-parks convergently on resume; M3 databases migrate and M3-stored runs
resume and reproduce; the full pre-M4 suite stays green.
