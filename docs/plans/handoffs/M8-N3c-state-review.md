# M8 N3c: state and resume review

Status: pre-implementation design, independently reviewed once and amended;
owner questions decided (below); implemented on this branch, with evidence,
deviations and limits in the
[M8 implementation record](M8-implementation-record.md#n3c--maintenance-activation-and-the-remaining-matrix-76).
The design text below is preserved as reviewed, with four marked exceptions:
the inventory table's line citations, which were refreshed after the move
onto `main`; decision 7, the reboot decision made after the PR review; the M1, M6 and A7
rows and the bundle-directory row of the crash matrix, which are corrected to
claim only what is now true; and the added M3a and M7a-M7c rows, plus the
matching crash-matrix row, for the re-anchor.
Base: written on `1ec4943` (N3b's review head), then applied onto `main` as
`0ddb247` (PR #101) after N3b merged. The inventory table's citations name
lines in that tree plus this PR's review fixes, except for the two fixtures
in row 15, which describe the state before N3c changed them. Branch:
`m8/n3c-matrix`. Reviewed head: `3ce85c4`.

The independent review (Codex `gpt-5.6-terra`, effort xhigh, job
`job_2036d3ab16a8`, worktree mounted read-only, no GitHub access) returned "do
not implement yet": six P1, seven P2 and one P3. Each premise was reproduced
against source before it was kept. This revision adopts the accepted findings;
the rest are recorded with reasons under [Review disposition](#review-disposition).
By owner instruction there is exactly one review pass: these amendments have
not been re-reviewed.
Scope: N3c of [issue 76](https://github.com/sushiHex/constructicon/issues/76),
the remainder after N3a (merged, #89) and N3b (#97).
Authority: [M8 rev 3, N3](../milestones/M8-live-executors-rev3.md) lines 89-116
and [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md)
lines 167-204 (binding, lock and maintenance), 228-254 (mode and overage) and
256-287 (non-widening and egress). Rev 2 N3 lines 198-209 are retained by
rev 3:91-93. This record does not amend any of them.

No implementation code exists for anything below. Every "test" named here is a
design obligation, not a claim about an executed test.

## Step one: inventory

N3c was asked to design only what N3a, N2 and N3b do not already prove. The
table is the result. "Proved" cites an existing test that asserts the fact;
"N3c" is new work in this slice; "N4" needs real vendor behaviour, a
credential or a live session and is carried, not simulated.

| # | Criterion (rev 3 N3) | Already proved | N3c (new) | N4 |
| --- | --- | --- | --- | --- |
| 1 | Maintenance exclusion (rev 3:92-93; rev 2:198-204 "recheck zero acquisitions/processes while holding the account lock") | The retained lock excludes a second holder and hands off (`test_operator_store_containment.py:140`); the supervisor keeps it through controller death (`:163`); the lock spans the materialized lifetime (`test_codex_store.py:230`) | There is no maintenance party at all: no `src/` code writes `active.json` (only tests and the CI builder, `build_m8_store_fixture.py:73-91`). N3c adds the offline maintenance helper that takes that same lock, and the tests that it waits for an idle holder and changes nothing on timeout | Requesting quiescence of a deployed host |
| 2 | Crash before/after durable withdrawal; no store mutation before withdrawal (rev 3:97-99; ADR 0021:193-198) | Reader refuses an absent selection (`test_operator_store.py:82`, `test_operator_store_restart.py:126`) | Withdrawal does not exist. N3c adds a durable withdrawal record and a store locator exposed only after it is durable; injected-failure and process-death crash points | Power-loss durability of the host filesystem |
| 3 | Crash before/after descriptor publication | No-replace publication, temporary never a descriptor, short write (`test_operator_store_publish_faults.py:11`, `test_operator_store_publication.py:230`, `test_operator_store_restart.py:126`) | One unpinned state: an orphaned `.pending-*` from a killed publication. `_descriptor_names` refuses any non-generation name (`operator_store.py:505-506`), so it disables every check and every later publication. N3c pins that fail-closed state; it does not clean it | - |
| 4 | Crash before/after activation; no activation before fresh qualification; store presence or an old qualification record insufficient | Selection must name the exact descriptor and sealed binding (`test_operator_store_selection.py:21,31,40,63`); publication is not activation (`test_operator_store_restart.py:126`) | Activation does not exist (the CI fixture writes `active.json` directly, `scripts/ci/build_m8_store_fixture.py:73-91`). N3c adds atomic activation that requires a withdrawal record, a generation above its floor and a sealed identity bound to that generation. **Partial:** this proves "bound to a generation published after the withdrawal", not that qualification ran; the qualified identity is trusted operator input, like every conformance revision today (`codex.py:251-255`). Whether that meets "fresh qualification" is owner question 3 | Running qualification against a published, not-yet-active generation |
| 5 | No stale provider accepting a retired selection | Initial, pre-launch and terminal checks reread the selection (`test_codex_store.py:230,286`; `test_operator_store.py:96,180`) | Only the composition with the new helpers: a materializer waiting on the lock during maintenance refuses after it; an old-generation reader refuses after activation in a fresh interpreter | - |
| 6 | Refresh: qualified file replacement permitted | Store writes, unlink and child-directory creation keep the binding (`test_operator_store_containment.py:54`); the directory link count is not identity (`test_operator_store.py:153`) | The native fixture never *replaces* an existing file. N3c adds an in-place truncate-and-rewrite (the pinned store's own save pattern, account preflight lines 123-125) and a rename-over replacement to that Linux fixture, with all three checks accepting | Real refresh semantics |
| 7 | Store-root and lock substitution refused | Same-path replacement after a real restart (`test_operator_store_restart.py:101`), during the lock wait (`test_operator_store.py:180`), at the terminal check (`test_codex_store.py:286`) | Nothing | - |
| 8 | An alias acquiring a second lock refused | Store symlink and lock hard link (`test_operator_store_restart.py:172`) | The mount-topology checks (`operator_store.py:371-399`, `:445-451`) have **no test and no mutant** in `scripts/check_m8_n3a_mutations.py`. A bind-mount alias is the one alias class left unproved. N3c adds portable and Linux proofs | - |
| 9 | Initial and terminal checks load-bearing | N3a mutants "initial readiness requires a sealed binding observation" and "terminal phase rechecks the retained binding" are assertion-killed (`check_m8_n3a_mutations.py:105-133`) | Nothing | - |
| 10 | Maintenance produces a new generation an old manifest cannot materialize | Generation changes the revision (`tests/core/test_native_operator_contracts.py:497`); activation refuses a changed revision (`runtime/registry.py:693-698`, `tests/runtime/test_activation.py:58`); an old sealed binding refuses a newer active one (`test_operator_store.py:82`) | "Every maintenance assigns a new generation" is not enforced: nothing stops an operator re-activating the withdrawn generation over a mutated store. N3c's activation floor makes it mechanical. The recovery half of ADR 0021:192-193 ("recovery disposes their existing acquisitions") is **not** met by the current walker for a new-generation assembly (see Inputs, "Recovery ordering"); N3c does not design it (owner question 6) | - |
| 11 | Cleanup leaves persistent vendor state alone | Reconcile leaves the store root in place (`test_codex_adapter.py:630`); a retargeted alias leaves a marker intact (`test_codex_store.py:187`) | Byte-identity of harmless store markers after close, reconcile, withdrawal and activation (Linux), and after close and reconcile over a real directory (portable) | - |
| 12 | Account/configuration change before and during a turn never widens callbacks, startup helpers, destinations, mounts or writes, even without a principal-change signal | Callbacks: exact catalog and parameters (`test_codex_write_protocol.py:78,89`), unknown methods never dispatch (`test_codex_write.py:478`), native requests are damage (`test_codex_adapter.py:889`), namespaced calls refused by the pinned binary (`test_native_codex_mediation.py:159`). Destinations: sealed policy only (`test_egress.py:570`, `test_native_egress_containment.py:498`). Mounts: fixed argv (`test_native_store_launch.py:49,64`). Writes: native-only store (`test_operator_store_containment.py:54`). None of these consults an account reading | The store as a cross-acquisition channel: content written into `/vendor-store` by one acquisition does not change the next acquisition's argv, and a planted executable runs with the zone's authority only, through the real N3b relay and leaf (Linux) | Which files the pinned client reads as configuration or helpers once `CODEX_HOME` is routed; cloud-managed settings |
| 13 | Subscription-to-API mode change refused without fallback | API key, Bedrock, provider override refused (`test_codex_protocol.py:351,358`); a switch at either reading refuses (`test_codex_adapter.py:1235,1759`); an `account/` notification refuses (`:824,843`); one launch only (`:1566`) | A pin that the refusal is followed by no further request of any kind (exact method list, one launcher call) | A session that misreports its own mode (N2 limit, `codex_protocol.py:20-24`) |
| 14 | Pre-model refusal with no model request and closed callbacks; a shared TLS destination is not phase proof | Pinned binary refuses at the pre-turn gate with zero model requests (`test_codex_native.py:139`, `peer.requests` empty at `:127`); READ pre-turn refusal sends no thread or turn (`test_codex_adapter.py:736`) | WRITE is unproved: no test refuses a WRITE conversation at the pre-turn gate and asserts `thread/start` (which carries `dynamicTools`) was never sent | Real startup traffic through the relay; the relay cannot tell initialization from inference and N3c claims no phase fact from egress |
| 15 | Overage limit behaviour independent of auth-mode labels; unknown enforcement cannot qualify an overages-forbidden profile | The two policies are distinct sealed revisions (`test_native_operator_contracts.py:375`, `tests/api/test_native_operator_admission.py:260`) | **The live gap.** `subscription_overage` is read by nothing in `src/` except its declaration (`core/native_operator.py:150`). Two fixtures with `"forbidden"` reach the accepting path with `unavailable_reasons=()` (`test_codex_adapter.py:138`, `test_codex_write.py:100`). N3c forces an unclearable reason on a forbidden profile, and pins the adapter's limit-reached behaviour | The vendor's mechanical refusal at the included limit; any positive enforcement fact |
| 16 | Credential-free Linux Actions; no secret archived | N3a/N3b evidence discipline | This slice's own `n3c-*.json` | Both |

### Inputs checked against source

- **Overage research (orchestrator-verified, re-checked here).** I fetched the
  pinned source (`3d2ee51`, tag `rust-v0.153.4`) read-only with `gh api`:
  - `Turn` (`app-server-protocol/src/protocol/v2/thread_data.rs:366-386`) has
    `id, items, itemsView, status, error, startedAt, completedAt, durationMs`.
    It has no `rateLimits`, and no `output`, `model` or `usage` either. So
    `observe_turn` (`codex_protocol.py:1026-1030`) finds none of the four
    against the pin, and `rate_limit` is `None` (`_rate_limit(None)`,
    `:930-931`), not merely `is_using_overage=None`.
  - `usingOverage` occurs in none of `v2/account.rs`, `v2/turn.rs`,
    `v2/thread_data.rs`, `v2/shared.rs`, `v2/notification.rs` or
    `protocol/common.rs`.
  - Spend control is readable only through the `account/rateLimits/read`
    request: `RateLimitSnapshot` (`v2/account.rs:565-576`) carries `credits`,
    `individualLimit`, `spendControlReached` and `rateLimitReachedType`. The
    comment on `spendControlReached` says `None` is "unavailable".
  - The in-turn `account/rateLimits/updated` notification
    (`common.rs:1907`) is refused by the adapter's `account/` namespace rule
    (`codex.py:496-498`). That is the recorded forward cost
    (`M8-implementation-record.md:937-945`). The existing parametrization
    (`test_codex_adapter.py:840`) names `account/rateLimits/changed`, a name
    that does not exist at the pin. The namespace rule refuses both, but the
    real name is not pinned.
  - A failed turn carries `error.codexErrorInfo`, whose members include
    `usageLimitExceeded` and `rateLimitExceeded` (`v2/shared.rs:74-81`,
    camelCase). `TurnStatus` is `completed | interrupted | failed | inProgress`
    (`v2/turn.rs:32-37`).
- **The production launch installs no vendor configuration.** `codex.py` never
  sets `CODEX_HOME`, and the launcher's native environment is `HOME=/tmp/home`
  on a tmpfs (`linux.py:331-333`). The store is bound at `/vendor-store`
  (`linux.py:341`), which no configuration names. The N3a record says the same
  (`M8-implementation-record.md:1142-1144`). Configuration read from the store
  is therefore not reachable in this slice. It becomes reachable when N4 routes
  `CODEX_HOME`.
- **The workload may execute anything it can write.** The workload AppArmor
  profile has `allow ix /**` (`scripts/ci/constructicon-m8-launch.apparmor`),
  and bubblewrap binds the store without `noexec`. A native process can
  therefore write and run a helper. What bounds it is the zone, not the exec
  rule. That is why row 12's Linux proof exists.
- **Operator-store laws are digests of the module's own source**
  (`operator_store.py:920-922`). Any N3c edit to `operator_store.py` changes
  `BINDING_LAYOUT_LAW` and `BINDING_MOUNT_LOCK_LAW`. Every existing descriptor
  then refuses until republished. That is intended, as N3b's runtime-digest
  change was. The CI fixture publishes afresh on every run.
- **The metadata ownership law is not the publisher's.** `_publish_new`
  creates files `0600` owned by the caller (`operator_store.py:528-531`), and
  the CI builder then chowns and chmods them to `root:<service group> 0440`
  (`build_m8_store_fixture.py:94-103`) so that the unprivileged service can read
  them. A descriptor published by the unmodified publisher during maintenance
  would therefore be unreadable by the service after activation (review F3).
  Both writers must produce the readable form themselves. The reader only
  requires root ownership and no group or world write bit
  (`operator_store.py:437-442`), so it does not catch an unreadable file until
  the open fails.
- **Publication takes no lock** (`operator_store.py:634-738`; the only `_flock`
  call is `:823`). A descriptor or its `.pending-*` can therefore appear while a
  provider holds the lock and lists `descriptors/` (`:805-811`), or while
  maintenance computes its floor (review F1, F8).
- **Recovery ordering.** `Walker` activates the manifest against the registry
  (`walker.py:379`) before it reconciles stale leases (`walker.py:503`,
  `:1151-1200`). So an old-generation manifest under a new-generation assembly
  refuses before any stale acquisition is reconciled. The provider's own
  `reconcile` also refuses a reference whose binding digest differs from its
  sealed one (`codex.py:1941-1948`).
- **The pinned client retries a provider failure until the owned deadline**
  (`test_native_startup.py:177`). A vendor-internal retry is bounded by the
  acquisition deadline; it is not an adapter retry or a mode fallback.

## Design

Three changes, and the rest is tests.

### 1. Maintenance: one record, two offline helpers (`operator_store.py`)

**One new state of `active.json`.** Today it is absent (disabled) or an active
selection. N3c adds a withdrawal record:

```json
{"generation_floor": F, "key": K, "schema_version": 1}
```

`_active` refuses it by shape (`operator_store.py:244-247`), so every provider
check reads it as "unavailable", exactly as it reads absence. No reader
changes. `F` is the highest descriptor generation present when the record was
written. Descriptors are immutable and never deleted, so `F` never decreases.

**One metadata ownership law for both writers.** A new
`_seal_metadata_fd(fd, directory_fd)` sets the file's group to the directory's
group (`fchown(fd, -1, gid)`, leaving the owner as the writing process, which is
root in production and which the reader already requires) and its mode to
`0440`. `_publish_new` calls it before its `link`, so a descriptor or anchor is
readable by the service the moment it is published (review F3). Keeping the
owner unchanged is what lets an unprivileged Linux test exercise the real
primitive (review F4); root ownership stays the reader's check.

**`_replace_metadata(directory_fd, name, raw)`**, a platform primitive beside
`_publish_new`. It creates `.pending-<hex>` exclusively, loops the write, calls
`_seal_metadata_fd`, `fsync`s the file, `os.replace`s it over `name` and
`fsync`s the directory. A failure unlinks the temporary if it still exists and
re-raises. It is the only writer of `active.json`. Portable tests substitute it;
Linux unit tests run it for real.

**Waiting.** Each helper takes `wait_s`, which must be a finite `int` or
`float` (not `bool`) and at least 0. It makes one `LOCK_NB` attempt, then polls
every 10 ms against `time.monotonic()` until the deadline; `wait_s=0` means
exactly one attempt. A timeout is a fixed-text refusal (review F9).

**Publication joins the lock** (review F1, F8). `publish_descriptor_offline`
gains `wait_s: float = 0` and takes the retained lock, by the same rule, after
its fixed children exist and before it reads the anchor or the inventory; it
holds it until its descriptor is published. Every existing caller runs with no
holder (the CI builder, `test_operator_store_restart.py`), so they are
unchanged. Two consequences: the inventory any lock holder reads cannot change
under it, which is what makes the floor sound; and the N3a race where a turn's
terminal check lists a publication's `.pending-*` is closed rather than carried.
Because flock is per open file description, publication cannot run inside a
`StoreMaintenance` context; the sequence is maintain (and log in), exit,
publish, qualify, activate.

**`maintain_offline(root, key, *, wait_s) -> StoreMaintenance`**, a synchronous
context manager:

1. Validate the key; `_open_bundle` (every trusted-ancestor, mode, owner and
   mount check, unchanged); read and check the anchor.
2. Take the retained lock by the waiting rule above. On timeout, raise a
   fixed-text `ContractViolation`. Nothing was written.
3. Under the lock, reopen the bundle and require the bundle, store and lock
   identities to equal the ones held (the N3a lesson: "a held check reused
   identities captured before a lock wait", `M8-N3a-state-review.md:263-265`).
   Factor the comparison already inline in `check_held`
   (`operator_store.py:852-856`) into one helper that both use.
4. Read `_descriptor_names` under the lock. `F` is the maximum, or 0.
5. `_replace_metadata(bundle_fd, "active.json", withdrawal(F))`. This runs
   whatever the previous state was (absent, active, a withdrawal or malformed):
   withdrawal only disables, and `F` is computed from the inventory, not from
   the previous record.
6. Only now construct the `StoreMaintenance` receipt, whose `store_path` is the
   locator the operator's vendor login may mutate. `__exit__` closes every
   descriptor (releasing the lock) and writes nothing. It never activates.

Holding the flock *is* the affirmative "zero owned acquisitions or processes"
fact that ADR 0021:186-188 and rev 2:203-204 require. Every materialized handle
retains that open file description from materialization through close
(`codex.py:1318-1350`, `:1655-1706`), and every supervisor inherits it until its
descendants are reaped (N3a, `test_operator_store_containment.py:163`).
`LOCK_EX|LOCK_NB` succeeds only when no other description holds it.

**`activate_offline(root, key, generation, *, qualified, wait_s)`**, where
`qualified` is the `NativeOperatorStoreIdentityV1` that qualification produced:

1. Steps 1-3 as above.
2. The current `active.json` must be a strict withdrawal record for this key.
   Absent, active, malformed or another key: refuse. **Every activation follows
   a durable maintenance record.**
3. Require `generation > F`. Descriptor names are unique and never reused, and
   publication now runs only under the lock that maintenance held from its
   inventory read through its durable replace. So descriptor `generation` was
   published after the withdrawal was durable. A qualification record for any
   generation that existed before the maintenance is therefore refused, and so
   is re-activating the withdrawn generation over a store the maintenance may
   have changed. This bounds *which* generation a qualification record can name;
   it does not prove that qualification ran (see Limits and owner question 3).
4. Read descriptor `generation` and run the descriptor half of today's
   `_check_selection` against `qualified`. Implement this by moving that body
   into `_check_descriptor(opened, descriptor, *, key, generation, sealed)`,
   which `_check_selection` then calls with `self.key`, `active.generation` and
   `self.sealed` after reading `active.json`. It checks the descriptor's key and
   generation against the expected ones (today `operator_store.py:783-788`,
   review F7), the derived binding digest against
   `sealed.operator_binding_digest`, both current laws, the instance re-derived
   from the live store, the live bundle, store and lock identities, and the
   same-instance history. The two active-record digest comparisons stay in
   `_check_selection`. One law, two callers.
5. Build the active body, validate it with the strict `_active` reader, and
   `_replace_metadata` it. Release the lock.

**What is not added.** No journal record, service, scheduler or runtime
maintenance API. No import from `codex.py` or any runtime path. The only
changes to `publish_descriptor_offline` are the lock and the ownership law. No
cleanup of stale temporaries. No new reader branch. Normal execution cannot run either helper successfully: the bundle is
`root 0750` (`build_m8_store_fixture.py:102-103`), so the runtime user cannot
create the temporary, and a Linux test pins that refusal.

**Why helpers at all, rather than tests over hand-made states.** ADR 0021:202-203
asks for physical tests of the configuration's "atomicity/durability and
old-provider refusal". Atomicity and durability are properties of a writer, and
none exists. Hand-written states test the reader, which N3a already did
(`M8-N3a-state-review.md:96-100`). This is owner question 1.

**N3a mutation anchors move.** Eleven N3a mutants target
`BindingStore._check_selection` source (`check_m8_n3a_mutations.py:176-258`).
The three that compare the active record itself (its key, descriptor digest
and binding digest) stay. The eight that compare the descriptor (its generation
against the expected one, the sealed identity, the laws, the live objects and
the history) retarget to `_check_descriptor`, with `self.sealed` and
`active.generation` in their anchor text becoming the parameters and their
killing tests unchanged. All 47 must still kill by assertion.

### 2. Overage availability (`codex.py`)

```python
OVERAGE_NOT_ENFORCED = (
    "an overages-forbidden profile has no proved refusal at its included limit"
)
```

In `CodexOperatorProvider.__init__`, next to the forced store reason
(`codex.py:1859-1861`): if `profile.subscription_overage == "forbidden"` and the
reason is absent, append it. No parameter, flag or label clears it. The
condition reads the sealed overage literal and nothing else: not
`authentication`, not `account_assurance`, not `ExpectedAccount.plan_type`, and
not any account reading (those happen only after `acquire`, which the reason
already refuses, `codex.py:1877-1878`).

What this proves credential-free: an overages-forbidden profile cannot be made
available by an empty reason tuple, whatever its labels say. That is ADR
0021:247-248 read mechanically, because nothing in this repository can supply
the "proved mechanical refusal at the included limit". What it does not prove:
that any vendor arrangement refuses at the limit. That is N4, and the positive
fact that would lift this reason has no field in the sealed identity (owner
question 2).

`operator_authorized` is unchanged: the sealed literal is the operator's
recorded approval, as it is today. The two accepting-path fixtures that
currently say `"forbidden"` (`codex_profile()`, `test_codex_adapter.py:111-139`;
`write_profile()`, `test_codex_write.py:73-101`) become `operator_authorized`.
Their subject is protocol and custody, not overage, and a forbidden fixture can
no longer acquire. No other test constructs the production provider with a
forbidden profile (`grep`, 2026-09-22).

The adapter has no overage branch, and N3c adds none. The limit-reached
behaviour is pinned as it is today (Proof plan, C5-C7).

### 3. Nothing else in `src/`

Everything else in the inventory is tests over existing code: refresh
replacement, bind-mount alias, cleanup markers, store persistence, the WRITE
pre-gate, the no-fallback pin, the pinned `account/rateLimits/updated` name and
cross-generation recovery. The one exception is a mechanical extraction for
testability: `_mounts_below` reads `/proc/self/mountinfo` inline
(`operator_store.py:333-335`). The bounded read moves into a `_read_mountinfo()`
primitive so the parse runs portably with only the read substituted.

## Lifecycle walk

The new operator-store code is synchronous. It contains no `await`, so its
interleavings are process death and concurrent processes, not event-loop
resumes. The awaits that matter are the provider's, run while a maintenance
process may hold or release the lock. "Assumes" names what the next step
relies on; "checks" what it verifies affirmatively.

### Provider awaits with maintenance in another process

| Point | What can be true when control arrives | Next step assumes vs checks | A raise leaves / a `finally` publishes |
| --- | --- | --- | --- |
| `await guard_owner.__aenter__()` and the first `await self._require_open()` (`codex.py:1327-1329`, `:1303-1305`) | Any maintenance, publication or activation state, including a partial one in another process | Nothing about the store is read yet: control and closure only (existing) | Guard released by `_release_custody` (`codex.py:1354-1358`); nothing of the store opened |
| `open_candidate` (sync, before the lock, `codex.py:1330`) | Maintenance may be about to withdraw, holding the lock, or finished | Reads a selection it does not trust: it is reread under the lock | A withdrawal record or absence refuses here: nothing held, candidate closed (`operator_store.py:768-776`) |
| `acquire_lock` loop: `await check_closure()`, `await asyncio.sleep(0.01)` (`operator_store.py:823-826`) | Maintenance, then publication, then activation may each have held and released the lock, one after another, in any number of rounds | Control and closure are checked on every resume (existing) | Cancellation closes the candidate (`:838-840`) |
| Lock acquired, `_check_selection(candidate)` (`:829`) | A complete withdraw, publish and activate cycle ran during the wait. The candidate's descriptors are the pre-wait objects; if maintenance replaced the store root, the candidate's store descriptor is the old object | Checks: selection reread now. A withdrawal refuses; an activated N+1 refuses on `self.sealed` (`:794`); a replaced root refuses on identity (`:800-802`) | Refused, candidate closed. **This is "no stale provider accepting a retired selection"** |
| `await check_closure()` after the lock, then `check_held` (`:830-833`) | Nothing can change `active.json` or `descriptors/` now: all three writers need this lock (publication only after review F1; before it, a `.pending-*` could appear here and refuse the check) | `check_held` reopens and rechecks anyway (existing) | - |
| A publisher or helper started while this handle is materialized | It polls the flock and fails; after `wait_s` it refuses having written nothing | The failed `LOCK_NB` is the fact | No `.pending-*` is created: publication creates its temporary only after taking the lock |
| Materialized and idle, until `close` | Maintenance polls the flock and fails | The helper assumes nothing; the failed `LOCK_NB` is the fact | The helper times out having written nothing |
| Execute: `_require_open`, probe, exchange (`codex.py:1468`, `linux.py:393`) | Lock held by the handle and inherited by the supervisor | Selection stable against the helpers; the post-probe (`codex.py:1487-1495`) and terminal (`:1526-1531`) checks still reread | Existing |
| Controller death mid-exchange | The supervisor keeps the lock until the native tree is reaped | Maintenance waits until quiescence (N3a owner-death evidence) | - |
| `close` (`codex.py:1645-1710`) | Joins owned work, then drops its descriptors: the lock is released only after the supervisor's copy too | The helper's next `LOCK_NB` succeeds only then | - |
| A reaper for an old-generation run | New assembly refuses the old manifest at activation (`walker.py:379`) before reconciling; an old-generation assembly reconciles (`codex.py:1924-1957` never reads the selection) and cannot materialize | Checks: binding digest in the reference against the sealed one (`codex.py:1941-1948`) | Disposal only; never upgrades. S12/S13 prove the provider half; the walker never reaches it under a new-generation assembly (review F5, owner question 6) |

### `maintain_offline` (a separate operator process)

| Point | State on disk if the process dies here | What the next step checks | What a raise leaves |
| --- | --- | --- | --- |
| M1 open bundle and anchor, no lock | Unchanged | *(Corrected after the PR #101 review.)* The anchor names this bundle exactly, or, for maintenance only, a reboot of the same physical bundle (decision 7). This pre-lock reading decides nothing: M3a decides again | Descriptors closed by `_open_bundle`'s own `except` (`operator_store.py:413-417`) |
| M2 flock polling | Unchanged; a holder exists | The failed `LOCK_NB` itself | Timeout refusal; the `finally` closes descriptors; nothing written or yielded |
| M3 reopen under the lock, compare identities | Unchanged | Bundle, store and lock identity equal to held | Refusal; nothing written |
| M3a *(added after the PR #101 review)* anchor read again under the lock | Unchanged | The same rule as M1, decided now. An anchor substituted during the wait refuses (S, "an anchor substituted during the lock wait") | Refusal; nothing written |
| M4 inventory read | Unchanged | `_descriptor_names` refuses an orphaned temporary or an unknown name | Refusal; the operator removes the orphan by hand (limit) |
| M5 temporary written, `fchown`, `fchmod`, `fsync` | Previous `active.json` intact; an inert `.pending-*` in the bundle directory (the reader never lists the bundle directory) | - | The primitive unlinks the temporary; previous state intact |
| M6 `os.replace` done, directory `fsync` not done | After process death, the withdrawal is visible and the binding is disabled. *(Corrected after the PR #101 review.)* After power loss the host reboots. The anchor and every descriptor then name the old boot, so every provider refuses whichever record survived, and only maintenance (decision 7) can restore the binding. The store was never exposed, so there was no mutation to protect. Whether the replace itself survived is not measured | - | The primitive raises; the receipt is never constructed |
| M7 directory `fsync` done | Withdrawal durable. Disabled | - | - |
| M7a *(added after the PR #101 review; only after a reboot)* withdrawal durable, anchor not yet rewritten | Withdrawn, and the anchor still names the previous boot. Every provider, publication and activation refuses. A rerun of maintenance re-anchors. Proved by an injected failure (S, "a failed re-anchor leaves the withdrawal"); process death at this point is **unproved** on Linux | - | Refusal; the receipt is never constructed |
| M7b anchor temporary written, not renamed | As M7a, plus an inert rename temporary in the bundle directory. That rests on the same reasoning as M5, which R2's kill point proves only for the withdrawal's temporary. Process death here is **unproved** | - | The primitive unlinks the temporary |
| M7c anchor renamed, directory `fsync` not done | Process death: withdrawn with the repaired anchor visible. Power loss: either anchor may survive, and the host has rebooted again, so the next maintenance decides afresh. The primitive's failure path is U4's; process death inside the re-anchor is **unproved** | - | The primitive raises; the receipt is never constructed |
| M8 receipt constructed, `store_path` exposed | Operator mutates the store (vendor login) | The operator assumes the procedure; nothing here observes the mutation (no content hash, ADR 0021:170-171) | - |
| M9 `__exit__` | Lock released; still withdrawn | - | Closes descriptors; writes nothing; never activates |

### `activate_offline`

| Point | State on disk if the process dies here | Checks | What a raise leaves |
| --- | --- | --- | --- |
| A1-A3 as M1-M3 | Withdrawn | Identity under the lock | Nothing written |
| A4 read state | Withdrawn | A strict withdrawal record for this key | Absent, active, malformed or another key: refuse |
| A5 floor and descriptor | Withdrawn | `generation > F`; `_check_descriptor` against `qualified` and the live objects | Refuse; withdrawn |
| A6 temporary written and `fsync`ed | Withdrawn; inert temporary | - | Temporary unlinked |
| A7 `os.replace` done, directory `fsync` not done or failed | Process death: new selection active. *(Corrected after the PR #101 review.)* Power loss: after the reboot every provider refuses, whether or not the new selection survived, because the anchor and the descriptors name the old boot. Recovery is reboot, maintain, publish, activate (decision 7). Durability of the replace is not measured | - | Raise. Defined rerun: a second activation refuses because the state is active; a second maintenance withdraws again. The operator learns the state by reading it with the strict readers, never by assuming (U4) |

### `publish_descriptor_offline` (changed: lock and ownership)

| Point | State on disk if the process dies here | Checks | What a raise leaves |
| --- | --- | --- | --- |
| P1 fixed children provisioned, `_open_bundle` | Unchanged metadata | Existing N3a checks | Existing |
| P2 lock taken (waiting rule) | Unchanged | The failed `LOCK_NB` while any holder exists | Timeout refusal; nothing written |
| P3 anchor and inventory read under the lock | Unchanged | Existing history check | Existing |
| P4 descriptor temporary written, sealed to `0440` and the directory's group, `fsync`ed | Orphaned `.pending-*` in `descriptors/` if killed here: disabled for every reader until an operator removes it (S10) | - | `_publish_new`'s `finally` unlinks it (`operator_store.py:555-558`) |
| P5 linked, temporary unlinked, directory `fsync`ed | Descriptor published, not active | - | - |
| A8 durable | Active | Providers sealed to this generation accept; every other generation refuses | - |

**Latches, none of which resets:** the handle's `entered`, `executed` and
`closed`; `StoreMaintenance.closed`; the durable floor `F`, which only rises
because descriptors are never deleted; and the rule that an activated
generation is always above the last floor, so a generation once withdrawn is
never active again.

**No `finally` constructs a receipt or writes a selection.** The receipt is
built in straight-line code after the directory `fsync` returns. Every
`finally` only closes descriptors or unlinks its own temporary.

## Crash and restart matrix

| Last completed fact | Disk | Every reader | Proof |
| --- | --- | --- | --- |
| Maintenance died before the replace (M1-M5) | Previous selection | Previous behaviour; store never exposed | S2 (injected), R2 (SIGKILL before the replace) |
| Maintenance died after the replace (M6-M9) | Withdrawal record | Disabled; old and new sealed both refuse | S3, R2 (SIGKILL after the replace) |
| Publication died with its temporary linked | Orphaned `.pending-*` in `descriptors/` | Disabled: the inventory refuses; publication and maintenance refuse until an operator removes it | S10 |
| Descriptor N+1 published, not activated | Withdrawal record + descriptor | Disabled | S5, R3 |
| Descriptor N+1 published *before* the maintenance | Descriptor ≤ floor | Activation of N+1 refused; N+2 required | S6 |
| Activation died before the replace | Withdrawal record | Disabled | S7 |
| Activation died after the replace | Active N+1 | Sealed N+1 accepts, sealed N refuses, in fresh interpreters | R3 |
| Re-activation of the withdrawn N attempted | Withdrawal record | Refused (`N ≤ F`) | S8 |
| Activation with N's sealed identity for N+1 | Withdrawal record | Refused | S9, R3 |
| Stale old-generation run after activation | Active N+1 | New assembly refuses the manifest before reconciling (unresolved, owner question 6); old assembly disposes, never materializes | S12, S13 |
| A helper killed with its `.pending-*` in the bundle directory *(corrected after the PR #101 review)* | Maintenance or activation killed before its rename: the previous `active.json` plus an inert temporary. Publication killed between linking and unlinking the anchor: a second name for `anchor.json` | Rename temporary: previous behaviour, because no reader lists the bundle directory (R2, temporary kill point). Anchor second name: every reader and helper refuses on the link count until an operator removes it (R7) | R2, R7 |
| Replace done, directory `fsync` raised (withdrawal or activation) | New record visible | Withdrawal: disabled, no receipt, body never ran. Activation: active; rerun refuses | U4 |
| *(Added after the PR #101 review)* Maintenance after a reboot died between the withdrawal and the re-anchor (M7a-M7c) | Withdrawal record; the anchor is stale or repaired | Disabled either way: the withdrawal refuses, and a stale anchor refuses too. A rerun completes | S (injected failure). Process death at M7a-M7c is **unproved**: no root-lane kill point sits inside the re-anchor |

## Negative inferences made affirmative

| Tempting inference | Affirmative replacement |
| --- | --- |
| The helper returned, so the store may be mutated | The receipt exists only after the directory `fsync`; an ordering recorder asserts replace and `fsync` precede the body (S1, U1) |
| An earlier observation showed no holder | The flock is taken and held for the whole maintenance; identities are compared again under it (S2, S4) |
| `active.json` is absent, so the binding was never active | Neither helper ever produces absence after a selection; activation refuses from absence (S7). Hand deletion is trusted-configuration tampering, outside the model |
| A descriptor and a qualification record exist, so activation is allowed | Activation needs a withdrawal record, a generation above its floor and a sealed identity whose binding digest is that generation's (S6, S8, S9) |
| The profile says `vendor_managed_subscription`, the plan reads `pro`, so no overage | The forced reason reads only the overage literal and is present under every label combination (C1); `rate_limit` stays `None` on a limit-reached turn with clean readings (C5) |
| No `rateLimits` in the turn, so no overage | `None`, never `False` (C5; `_rate_limit` returns `None` for an absent object, `codex_protocol.py:930-931`) |
| A failed turn at the limit means nothing was spent | Not claimed. The outcome is non-success and there is exactly one `turn/start`; spend is vendor-side (N4) |
| The planted helper was denied everything | It must first print a marker proving it ran (positive control), then its attempts are denied (N3) |
| The second launch looks the same | `LinuxLauncher.argv` for both launches is compared byte for byte (N3) |
| The store marker still exists after cleanup | Byte equality of its content, not existence (N2, S11) |
| A crash test passed, so the write is durable | Process death is not power loss; durability rests on `fsync` semantics and is a carried limit |
| The mount checks exist, so aliases are refused | They had no test. S14-S15 (portable) and U3 (Linux unit) make them load-bearing; R4 runs a real bind mount |

## Proof plan

Every case has a permitting and a refusing direction, and each file starts with
the permitting case.

**Portable** (Windows and Linux). `S` is
`tests/substrate/test_operator_store_maintenance.py`, built on `StoreWorld`
with `_replace_metadata` substituted by one that writes the in-memory metadata
and records events. `C` is `tests/substrate/test_codex_matrix.py`.

- S1 Permit: maintenance from an active selection writes the withdrawal record,
  then exposes `store_path`. Order recorded: lock, identity recheck, inventory,
  replace, body.
- S2 Refuse: a held lock (`lock_after` beyond `wait_s`) times out. The selection
  is byte-identical and the body never runs. A `_replace_metadata` that raises
  also leaves the body unrun.
- S3 Every provider refuses inside the body (open candidate: "active selection
  is unavailable"), sealed N and sealed N+1 alike.
- S4 A store identity replaced during the wait is refused after the lock, with
  nothing written.
- S5 Permit: maintain, publish N+1, activate N+1 with its sealed identity; a
  sealed N+1 provider materializes and executes to success.
- S6 A descriptor published before the maintenance cannot be activated;
  publishing the next one can.
- S7 Activation refuses from an absent, active, malformed or other-key state.
- S8 The withdrawn generation and any generation at or below the floor are
  refused.
- S9 Activation with N's sealed identity for N+1, a sealed identity with a
  wrong law, a descriptor whose store or lock identity differs from the live
  object, or a descriptor whose own key or generation differs from the
  requested ones is refused; a correct one is accepted.
- S10 An orphaned `.pending-*` among the descriptors disables selection,
  maintenance and publication; removing it restores all three.
- S11 Close and reconcile leave a harmless marker in a real store directory
  byte-identical.
- S12 An old-generation provider reconciles its stale acquisition after
  activation of N+1 and refuses to materialize.
- S13 A new-generation provider refuses the old-generation reference with no
  disposal.
- S14 and S15 `_mounts_below` with a substituted `_read_mountinfo`: no mount at
  or below the store is accepted; a mount at the store root with another
  mount id is refused; a mount below it is refused.
- S16 A materializer waiting on the lock while "maintenance" runs (the
  `check_closure` callback swaps the world's selection to a withdrawal, then to
  N+1) refuses after the wait, and a sealed N+1 materializer accepts.
- S17 Exiting the maintenance context releases the lock and activates nothing.
- S18 Publication while a holder exists (a materialized handle, or a
  maintenance context) refuses at `wait_s=0` with nothing written; after the
  holder closes it publishes (permit).
- S19 `wait_s` refuses `True`, `-1`, `nan` and `inf`; `0` makes exactly one
  `_flock` attempt.
- C1 Forbidden with `unavailable_reasons=()` publishes exactly
  `(OVERAGE_NOT_ENFORCED,)` and refuses `acquire`, for every combination of the
  plan labels exercised and with or without a binding. `operator_authorized`
  with `()` publishes `()` and acquires. `describe()` shows the reason.
- C2 A WRITE conversation refused at the pre-turn reading (null account)
  sends exactly `initialize, initialized, account/read`; the bytes never
  contain `dynamicTools`; a callback the peer emits early is never dispatched;
  the worker is never called. A clean WRITE reading proceeds (permit).
- C3 An API-key switch at the pre-acceptance reading: the methods are exactly
  the six of a clean run, with no request after the second `account/read`;
  one launcher call; the outcome is `unavailable`. The clean run is the permit.
- C4 `account/rateLimits/updated`, the pinned name, mid-turn discards the turn
  (the forward cost, pinned). Its docstring cites the pinned source
  (`codex-rs/app-server-protocol/src/protocol/common.rs:1907` at `3d2ee51`),
  which this review read with `gh api` and the independent reviewer could not
  reach (review F12).
- C5 A `turn/completed` with `status: "failed"` and
  `error.codexErrorInfo: "usageLimitExceeded"`, under clean identical
  readings: not success (today `ExecutorPartial` with the status fault), `rate_limit`
  is `None`, the six methods exactly, one launcher call. The same turn with
  `status: "completed"` succeeds (permit).
- C6 C5's peer additionally answers any `account/rateLimitResetCredit/consume`
  or `account/login/start`: those methods are never sent.
- C7 The limit-reached conversation behaves identically whichever overage
  literal the provider was built with (the conversation takes no profile, so
  this is an assertion that its bytes are equal).

**Linux unit** (unprivileged, `verify.yml`). `U` is
`tests/substrate/test_operator_store_replace.py`.

These run unprivileged because `_seal_metadata_fd` changes only the group, to
the directory's own group, which the test user owns (review F4). Root ownership
is not asserted here; the root lane asserts it.

- U1 The real `_replace_metadata` on a temporary directory: with `os.fsync`
  and `os.replace` wrapped by a recorder, the order is write, `fsync`
  (temporary), replace, `fsync` (directory); the result is `0440` with the
  directory's group. The same for a descriptor published by `_publish_new`.
- U2 A replace that raises leaves the previous file byte-identical and no
  `.pending-*`.
- U4 A directory `fsync` that raises after the replace: the new record is
  visible, the helper raises, no receipt exists and the body never ran; a
  second maintenance succeeds and a second activation refuses (review F10).
- U3 `_open_bundle` with only `_open_trusted_directory`, `_trusted_directory`
  and `_identity` substituted: a store or lock whose mount id differs from the
  root's is refused; equal ones are accepted.

**Linux root lane** (`test_operator_store_restart.py`, hosted runner, the
provisioning principal, fresh interpreters as today). `R`:

- R1 End to end: publish 1, activate by fixture, fresh read accepts; maintain
  (a harmless marker is written only inside the body); publish 2; activate 2
  with its sealed identity; sealed 2 accepts, sealed 1 refuses, in fresh
  interpreters run as `m8-service` (review F3: a root reader would hide an
  unreadable descriptor). `active.json` and `2.json` are `root:<bundle group>
  0440`.
- R2 A child process runs `maintain_offline` with `_replace_metadata` wrapped to
  print a line and stop before (and, separately, after) the real call. It is
  killed with SIGKILL. Before: the selection is unchanged, the body's marker is
  absent, a fresh reader accepts. After: a fresh reader refuses both
  generations.
- R3 The same for `activate_offline`, and activation with generation 1's
  sealed identity for generation 2 refused.
- R4 Two bundles: B's `store` bind-mounted from A's is refused; after
  `umount`, B is accepted. A bind mount below A's store is refused.
- R5 A waiting reader (a fresh interpreter blocked in `acquire_lock` while the
  test holds maintenance) refuses with sealed 1 after activation of 2.

**Linux service lane** (`test_operator_store_containment.py`, `m8-service`, the
provisioned fixture). `N`:

- N1 Refresh permit: the harmless native fixture truncates and rewrites
  `fixture-marker` in place and replaces a second marker by rename. The
  post-probe and terminal checks accept.
- N2 Cleanup: markers' bytes are unchanged after the acquisition closes.
- N3 Persistence, through the real N3b relay and leaf (review F11; it reuses
  the N3b containment harness, `test_native_egress_containment.py`, rather than
  the egressless N3a launch): launch 1's native writes `config.toml`,
  `hooks.json` and an executable `helper` into `/vendor-store`. Launch 2's native
  runs the helper, which prints a marker (the positive control) and then
  attempts `/workspace`, the bundle metadata, the lock, a write to `/`, a direct
  TCP connect, a host socket path, and a CONNECT through `/vendor-egress.sock`
  to the decoy. Each fails with its expected errno or relay denial, the allowed
  peer still accepts one CONNECT from launch 2 (same-run control), and
  `launcher.argv` for launch 2 equals launch 1's byte for byte. The planted
  files are removed in `finally`.
- N4 `maintain_offline` run as `m8-service` may take the lock (the service
  owns `retained.lock`) but cannot create its temporary in the root-owned
  bundle: it refuses with fixed text, and `active.json` is byte-identical.
  This is the affirmative form of "normal execution cannot rewrite it"
  (ADR 0021:201-202).

**Evidence.** `n3c-maintenance.json`, `n3c-refresh.json` and
`n3c-persistence.json` record the schema, `credential_free_fixture: true`,
`vendor_conformance_qualified: false`, booleans for each fact, and nothing
from the store or the metadata.

**CI.** One foundation-lane step, "Prove N3c maintenance, refresh and
non-widening", after N3b's: the root-lane file as root (it makes its own roots
under `/var/lib/constructicon-m8-launch`), then the service-lane file, then
`scripts/check_m8_n3c_mutations.py`. Add `n3c-*.json` to the artifacts and the
step to `PROOFS` in `tests/test_m8_containment_workflow.py`.

## Mutation inventory

`scripts/check_m8_n3c_mutations.py`, shared runner, assertion kills only. Every
mutant is killed by a portable or Linux-unit test. The `U` mutants (9-11, 15,
24, 27) report NOT PROVEN on Windows and are measured in Linux.

| # | Mutant | Killing test |
| --- | --- | --- |
| 1 | The context yields `store_path` before `_replace_metadata` returns (premature exposure, not receipt construction, review F13) | S1 |
| 2 | Maintenance skips `_replace_metadata` | S3 |
| 3 | Maintenance skips the flock loop | S2 |
| 4 | Maintenance skips the identity recheck under the lock | S4 |
| 5 | The floor is the previous active generation, not the inventory maximum | S6 |
| 6 | Activation accepts an active current state | S7[active] |
| 7 | Activation accepts an absent current state | S7[absent] |
| 8 | `generation > floor` becomes `>=` | S8 |
| 9 | `_replace_metadata` drops the directory `fsync` | U1 |
| 10 | `_replace_metadata` writes in place instead of replacing | U2 |
| 11 | `_replace_metadata` keeps `0600` | U1 |
| 12 | Activation skips the binding-digest comparison with `qualified` | S9 |
| 13 | `_check_descriptor` skips the live store identity | S9 (wrong store) and the retargeted N3a mutant |
| 14 | `_mounts_below` point check removed | S14 |
| 15 | `_open_bundle` store mount-id comparison removed | U3 |
| 16 | `_mounts_below` below-prefix check removed | S15 |
| 17 | `_descriptor_names` skips a non-generation name | S10 |
| 18 | The maintenance exit leaves the lock held | S17 |
| 19 | `reconcile`'s binding-digest comparison removed | S13 |
| 20 | The forced overage reason is removed | C1 |
| 21 | The forced reason also applies to `operator_authorized` | C1 (permit half) |
| 22 | The forced reason is keyed on `authentication` instead of the overage literal | C1 |
| 23 | Publication skips the retained lock | S18 |
| 24 | `_publish_new` skips `_seal_metadata_fd` (descriptor stays `0600`) | U1 (descriptor half) |
| 25 | Activation parses the withdrawal record without checking its key | S7[other-key] |
| 26 | `_check_descriptor` skips the descriptor's own key or generation (implemented as two mutants: 26 is the key half and 29 the generation half) | S9 (key/generation half) |
| 27 | The helper records the receipt when the directory `fsync` raises | U4 |
| 28 | `wait_s` validation removed | S19 |

Not mutated: qualification provenance, which has no mechanism in this design
(owner question 3).

N3a's 47, N3b's 43 and N2's 82 and 49 must still kill by assertion, after the
`_check_descriptor` retargeting.

Dropped as equivalent or structural: a mutant that writes the store in
`maintain_offline` (no code path writes it); one that reorders
`account/read` and `thread/start` (not expressible as a single replacement, and
C2 pins it); one on `_rate_limit` for C5 (N2 already mutates it).

## Limits carried

- **Power loss.** Process death is tested; power-loss durability rests on
  `fsync` of the file and the directory on the host filesystem, and is not
  measured anywhere. After the reboot a power loss implies, no provider
  accepts until maintenance runs (decision 7), whatever record survived.
- **The operator's procedure.** The helpers order withdrawal before exposing
  the locator; they cannot stop a trusted operator, or any same-uid host
  process, writing the store outside that context. The store is
  runtime-uid `0700` (`operator_store.py:37`). Same trusted-custody boundary as
  N3a and N3b.
- **Content is never observed.** No step detects that the store changed
  (ADR 0021 forbids hashing credential content). Withdrawal is what makes a
  change harmless, not detection.
- **Qualification is an input, not a proved event.** `activate_offline`
  checks that `qualified` names this generation's binding and current laws, and
  the floor guarantees that generation was published after the withdrawal. Its
  two conformance revisions are opaque, caller-supplied and never minted or
  checked here, exactly like the conformance revisions every launch identity
  already carries (`codex.py:246-250`). So N3c does **not** prove that
  qualification ran after the store mutation (review F2). That part of rev 3's
  "no activation before fresh qualification" stays open (owner question 3).
- **Qualifying a withdrawn generation.** Every provider refuses a generation
  that is not the active selection, by design (ADR 0021:198-200). How
  qualification runs against a published, not-yet-active generation is not
  designed here (owner question 3).
- **Orphaned temporaries** from a killed publication disable the binding until
  an operator removes them. Fail-closed; pinned by S10; no automatic cleanup.
- **Publication needs quiescence.** Because publication now takes the lock, it
  refuses (or waits up to `wait_s`) while any acquisition is materialized. This
  replaces the N3a race in which a running turn's terminal check could list a
  publication's temporary.
- **Old-generation recovery is not reachable from a new-generation assembly**
  (review F5, pre-existing). The walker activates the manifest against the
  current catalog (`walker.py:379`) before reconciling stale leases
  (`walker.py:503`), and a changed capability revision refuses activation
  (`registry.py:693-698`), so `CodexOperatorProvider.reconcile` is never
  reached. Only an assembly still publishing the old revision can dispose those
  rows. Their physical custody is already quiescent, since maintenance could not
  otherwise have taken the lock, but ADR 0021:192-193's "recovery disposes
  their existing acquisitions" is not met by any new-generation mechanism
  (owner question 6).
- **Store content is inert to constructicon, not to the vendor.** N3 proves
  the next launch's argv and the zone's reach are unchanged. Whether the pinned
  client reads configuration, hooks or skills from the store is N4, when
  `CODEX_HOME` is routed. The layout N4 chooses must not make the writable store
  a configuration root.
- **Mid-turn physical root substitution** is proved in halves: the terminal
  check's wiring portably (`test_codex_store.py:286`), the physical identity's
  sensitivity across interpreters (`test_operator_store_restart.py:101`). No
  single Linux test replaces the root during a live exchange, because the
  bundle is root-owned and the launcher refuses to run as root.
- **Overage.** Forbidden stays unavailable until a successor decision defines
  a positive enforcement fact. The adapter does not send
  `account/rateLimits/read`; interpreting `spendControlReached`, `credits` or
  `individualLimit` as enforcement is vendor semantics (N4). A limit-reached
  turn is published as partial with a status fault, not classified as a limit.
  `account/rateLimits/updated` still refuses a turn.
- **Phase.** No phase-separation claim is made from egress. The phase fact is
  the adapter's ordering (`codex.py:1091-1103`) plus the pinned binary's
  observed zero model requests before a turn; real startup traffic is N4.
- **Law digests move.** Editing `operator_store.py` changes both store laws;
  every existing descriptor refuses until republished.
- **Unexecuted until Linux CI runs**: U1-U4, R1-R5, N1-N4, and mutants 9-11,
  15, 24 and 27. Windows skips are not passes. The portable `StoreWorld`
  doubles prove parsing, ordering and lifecycle logic only; they prove nothing
  about flock, ownership, `fsync`, mounts or the supervisor.
- **Not re-reviewed.** These amendments, including the new publication lock and
  ownership law, have had no independent review (one-pass owner instruction).

## Rejected as unnecessary

- A maintenance service, a runtime maintenance API, or a journal record.
- A separate tombstone file, or unlinking `active.json` on withdrawal: the
  first makes withdrawal two non-atomic writes, the second loses the floor.
- Automatic cleanup of `.pending-*`.
- Requiring a maintenance record for publication. Publication takes the lock
  (review F1), which is what the floor needs; a record requirement would forbid
  N3a's accepted publish-while-active path for no further protected fact.
- Sending `account/rateLimits/read` or narrowing the `account/` refusal: both
  need vendor semantics this repository does not hold.
- Classifying a limit-reached turn as a new outcome kind.
- A mid-exchange root-substitution Linux test (see Limits).
- A Linux owner-death variant with the helper as contender: the helper uses
  the same `_flock` on the same file as the N3a contender.
- An in-zone `noexec` for the store: the zone, not the exec bit, bounds a
  helper, and N3 proves that.
- New L0 fields.

## Owner questions

### Decided (orchestrator, 2026-09-22, before implementation)

The questions below are kept as they were asked. These are the decisions and
their reasons; none reopens ADR 0021 or rev 3.

1. **Maintenance helpers: accepted.** `maintain_offline`, `activate_offline`
   and the withdrawal record as a third state of `active.json` are built as
   designed. The withdrawal record is ADR 0021's durable withdrawal.
2. **Overage: accepted, not blocking.** An overages-forbidden profile is forced
   unavailable and nothing in N3c can lift it. The lifting mechanism, a positive
   enforcement fact, is N5 work and is not built now (YAGNI). The
   `operator_authorized` literal is **not** the "approval and its bounds" of
   ADR 0021:249-250; that approval is N5's written authorization record. Until
   it exists, the default unavailability (vendor conformance unqualified) keeps
   every `operator_authorized` profile unavailable in production. Accepting-path
   fixtures may use `operator_authorized` under that stated condition.
3. **Fresh qualification: a recorded limit, not blocking #76.** The positive
   fact N3c proves is that activation requires a qualification record bound to
   a generation above the withdrawal floor. That the record's content came from
   a real qualification run is operator-supplied, the same trust boundary as
   every existing conformance revision (for example
   `physical_conformance_revision`).
4. **Generation discipline: accepted.** Publish g1, maintain and log in,
   publish g2, activate g2.
5. **Orphaned temporaries: manual repair.** It fails closed; no automatic
   cleanup (YAGNI). The operator procedure records it (implementation record).
6. **Old-generation recovery: operator procedure, not blocking.** Maintenance
   requires that no acquisition under the old generation is unrecovered. The
   mechanical check is the retained lock: every materialized acquisition and
   its supervisor hold it until reaped, so maintenance refuses while any
   old-generation acquisition is live (S20, with S2 and the N3a owner-death
   evidence). A durable stale row whose custody is already quiescent is not
   visible to that check. The procedure is to recover or cancel such runs under
   the old assembly before maintenance; that assembly's `reconcile` never reads
   the selection (S12), and a new-generation assembly refuses the reference
   without disposal (S13). No walker change.
7. **Reboot: maintenance re-anchors the same physical bundle** (decided after
   the PR #101 review, finding N3C-ASYNC-1). The N3a anchor records the
   bundle's full identity, including the boot id. So after any reboot every
   provider, publication, activation and maintenance itself refused, and
   nothing could recover the binding. That is a routine event on the M8-D2
   host, and ADR 0021:152-154 says availability stops *for maintenance*.
   Maintenance may now rewrite the anchor, under the retained lock and after
   the withdrawal is durable. It does so only when the anchored and live
   bundle agree on `handle_type`, `handle_hex`, `dev`, `ino`, `mode`, `uid` and
   `nlink`, and the boot id has changed; the mount id may differ. A different
   stable identity is a substitution and stays refused. So does a mount-id
   change within one boot (a remount, not a reboot). Two points go beyond the
   decision's list: `nlink` must also be equal, and the boot must actually
   have changed. Providers, publication and activation still require the
   anchor exactly, so a reboot needs maintenance rather than silent reuse (N3a
   state review:76-77). Every descriptor also records the old boot, so no
   earlier generation is accepted again. The sequence is: reboot, maintain,
   publish, activate. What this changes: the anchor now attests "this physical
   bundle, as last maintained in this boot", not "as first published".
   A follow-up attack found that the instance-history check matched old
   descriptors by instance, and the instance includes the boot id. After a
   reboot, a root-replaced `retained.lock` under the same physical store was
   therefore published, activated and accepted. Decided (option 1, enforced in
   code): publication and `_check_descriptor` compare stores by their
   boot-independent fields (`handle_type`, `handle_hex`, `dev`, `ino`). When an
   old descriptor's store matches, the lock must match on the same fields.
   That restores ADR 0020:230-235 ("not deleted or replaced while the binding
   exists") across boots. A real reboot still passes, because the physical
   lock is unchanged.

### As asked

1. **Maintenance helpers.** Are `maintain_offline` and `activate_offline`
   acceptable as offline provisioning helpers beside
   `publish_descriptor_offline`, with the withdrawal record as a third state of
   `active.json`? The alternative, testing only the reader against hand-made
   states, leaves ADR 0021:202-203's atomicity and durability with no writer
   to test.
2. **Overage.** Accept that an overages-forbidden profile is unavailable in
   N3c with nothing able to lift it, and that the accepting-path fixtures move
   to `operator_authorized`? Lifting it needs a positive enforcement fact bound
   into the identity; ADR 0021:297-322 lists no such field, so that looks like
   a successor decision at N4. Separately, and blocking for any claim about
   the authorized profile (review F6): is the sealed `operator_authorized`
   literal alone the "explicit operator approval of subscription-linked
   overage and its bounds" (ADR 0021:249-250), or must bounds be represented?
   The fixture move makes no such claim; it only keeps protocol and custody
   tests on the one profile the provider does not force unavailable. If the
   answer is "bounds must be represented", `operator_authorized` also needs a
   forced reason and the fixtures need another route, which is an L0 question.
3. **Fresh qualification (blocking for that criterion, review F2).** N3c
   proves activation is bound to a generation published after a durable
   withdrawal, with a qualified identity naming it. It cannot prove that
   qualification ran after the store mutation: the qualified identity is
   caller-supplied, like every conformance revision today. And the readers
   refuse any generation that is not active, so no qualification can yet run
   against a published, withdrawn-state generation. Is the trusted-input
   boundary acceptable for N3 with the qualification path deferred to N4, or
   does "no activation before fresh qualification" need an authority decision
   (for example a qualification record the activation can verify) before N3
   closes?
4. **Generation discipline.** Activation requires a generation above every
   descriptor that existed at withdrawal. First provisioning therefore publishes
   generation 1 (the empty layout), maintains, logs in, publishes generation 2
   and activates 2. Acceptable?
5. **Orphaned temporaries.** Keep the fail-closed manual repair, or have
   maintenance remove `.pending-*` under the lock?
6. **Old-generation recovery (pre-existing, review F5).** A new-generation
   assembly refuses an old manifest at activation (`walker.py:379`,
   `registry.py:693-698`) before the walker reconciles its stale leases
   (`walker.py:503`), so only an old-generation assembly can dispose them.
   Options: (a) record it as the operator procedure (recover or cancel runs
   under the old assembly before maintenance; physical custody is quiescent
   either way); (b) a walker change that reconciles stale rows of a refused
   manifest through the provider that minted them, which is runtime work with
   its own review. N3c designs neither. Which, and does it block closing #76?

## Review disposition

One independent pass: Codex `gpt-5.6-terra`, effort xhigh, job
`job_2036d3ab16a8`, read-only worktree at `3ce85c4`, no GitHub access (it
reported the issue and PR facts as unverified). Verdict: "do not implement
yet". Every premise below was reproduced against source before it was kept.
Classification follows AGENTS.md; only introduced and pre-existing findings
block.

| # | Finding | Class | Disposition |
| --- | --- | --- | --- |
| F1 | P1: publication takes no lock, so a descriptor published between maintenance's inventory read and its replace defeats the floor (`operator_store.py:634-738`; only `_flock` call is `:823`) | introduced | Adopted. Publication takes the retained lock before reading the anchor or inventory; the floor argument now rests on it; mutant 23, S18 |
| F2 | P1: `qualified` is caller-supplied opaque digests, so activation does not prove qualification ran after the mutation | design choice disagreement (the trust boundary is the one every conformance revision already has, `codex.py:246-250`) | Not adopted as a mechanism: no credential-free qualification exists to verify. The overclaim is removed: inventory row 4 now says "partial", the limit is rewritten, and owner question 3 asks whether the criterion needs an authority decision before N3 closes |
| F3 | P1: an N+1 descriptor published by the unmodified publisher is `0600` caller-owned, so the service cannot read it after activation; R1 used a root reader | introduced | Adopted. One ownership law (`_seal_metadata_fd`) for `_publish_new` and `_replace_metadata`; R1 reads as `m8-service`; mutant 24 |
| F4 | P1: an unprivileged U test cannot `fchown` to uid 0 | introduced | Adopted with a smaller fix than proposed: the primitive changes only the group (the owner is the writing process, root in production, and the reader already requires uid 0), so the U tests stay unprivileged and their mutants measurable; root ownership is asserted in R1 |
| F5 | P1: a new-generation assembly never reaches `reconcile` for an old manifest | pre-existing | Reproduced (`walker.py:379`, `:503`; `registry.py:693-698`). Recorded as a limit and owner question 6; not designed here, because the fix is walker work outside rev 3 N3's list and needs its own review |
| F6 | P1: treating the `operator_authorized` literal as approval conflicts with ADR 0021:249-251's "and its bounds" | design choice disagreement | Kept as owner question 2, now marked blocking for any authorized-profile claim. N3c claims nothing about it: the literal is clearable today, so the fixture move is not a widening, which the reviewer confirmed |
| F7 | P2: `_check_descriptor(opened, descriptor, sealed)` loses the descriptor key and generation checks (`operator_store.py:783-788`) | introduced | Adopted. Signature takes `key` and `generation`; S9 and mutant 26; the N3a anchor count is now three stay, eight move |
| F8 | P2: the lifecycle walk omits the guard and closure awaits and publication's `.pending-*` during a held lock | introduced | Adopted. Rows added; the publication race is closed by F1 rather than carried |
| F9 | P2: `wait_s` has no clock, validation or zero semantics | introduced | Adopted. `time.monotonic`, finite non-bool at least 0, one attempt at 0; S19, mutant 28 |
| F10 | P2: no test of a failure between replace and directory `fsync` | introduced | Adopted. U4 and a defined rerun behaviour; mutant 27 |
| F11 | P2: the persistence proof must run through the N3b relay and leaf | introduced | Adopted. N3 moves onto the N3b containment harness with a same-run relay control |
| F12 | P2: the `account/rateLimits/updated` name is unverified locally | introduced (evidence) | Adopted as provenance: the name was read from pinned source with `gh api` (`common.rs:1907` at `3d2ee51`); C4's docstring cites it. The reviewer's sandbox could not reach it, so this is my verification, not independent |
| F13 | P2: mutant 1 targeted receipt construction, which is unobservable; missing mutants | introduced | Adopted. Mutant 1 is now premature exposure; mutants 23-28 added. No provenance mutant, since there is no provenance mechanism |
| F14 | P3: "nothing but tests writes `active.json`" is false: the CI builder does | introduced | Adopted: row 1 now says no `src/` writer exists |

Reviewer statements accepted without change: holding the flock is a positive
"no materialized normal acquisition" fact within the cooperative model, not a
universal process census (the limits already say so); the withdrawal shape is
refused by every existing reader; the crash interpretations, including the
orphaned descriptor temporary, are correct; the overage forced reason is the
smallest credential-free proof and relies on no auth label; the mount, refresh,
WRITE pre-gate and overage work are genuine gaps.

Not verified by the reviewer, and so not counted as independent evidence: any
GitHub fact; any assertion or kill of the proposed tests and mutants, none of
which exist yet; and the behaviour of existing tests, whose execution history it
could not see.

These amendments have not been re-reviewed, by owner instruction.
