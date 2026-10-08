# M8 N5 Stage 3: the one READ turn

Status:
- **Part A (this PR), implemented:** the production host assembly and the host
  commands.
- **Part B, the next PR:** the read authorization, the attempt record, gated
  dispatch and the read graph.

Both merge before Stage 2 runs, and `codex.py` is frozen after part B (decision
S3-4).

Frozen text: M8-N5-state-review.md, Stage 3, decision 6, and the refusal and
retry rules.

**Reviews:**
- design v1: Fable (job_8aa1dc6b8038);
- evidence map: `stage3-seams` (session scratchpad).

## Owner decisions (2026-10-08), all on Fable's recommendation

- **S3-1. One attempt record per read authorization** is the one new durable
  artifact, serving both attempt accounting and the cross-reset consumption
  witness. Its two phases are an exclusive create at `acquire` (state
  `acquired`, proven not dispatched), then `intent` just before `turn/start` is
  written to the client.
  - It answers ADR 0021:164-165's "must stop for review".
  - It explicitly sets aside ADR 0018:331-332's rejection of "a durable
    executor ledger": one record per authorization is not a ledger.
- **S3-2. The three conformance revisions** (physical, authenticated startup
  and subscription mode) are the sealed qualification evidence digest `Q`, read
  from the store identity. `Q` names which qualification ran; it claims no
  conformance, and the evidence records `vendor_conformance_qualified: false`
  (rev3:156-157).
- **S3-3. The fixed READ task** is a literal inside the node function, under
  200 bytes, with no repository or account content. The function's source digest
  pins the literal; it would not pin a module constant.
- **S3-4. Stage 3's code merges before Stage 2 runs.** Stage 2's evidence
  records the adapter revision, which is a digest of all of `codex.py`. A later
  edit would invalidate g4.

## Part A: the production host assembly

**`substrate/executors/codex_host.py`** assembles the provider from installed
facts only. It reuses:
- the lane's launcher over the launch root;
- the session's sealed startup policy;
- `production_configuration()`, which must equal the session's `config.toml`;
- `RUNTIME_BINARY`;
- the bound vendor executable's digest;
- `BindingStore` over the operator store;
- `launch_identity`.

It adds:
- **`READ_PROFILE`:** the prepared model and effort, no tools, and the owner's
  `operator_authorized` overage.
- **`READ_GRANTS`:** that model and effort, network `allow`, and decision 6's
  120 s.
- **`sealed_account(store, evidence, installed)`,** the code twin of the
  runbook's `check_evidence` for a passing maintenance startup, so it holds
  without trusting that the runbook was followed:
  - the evidence is exactly the one sealed (its digest is both store
    revisions), read as one bounded, regular, duplicate-free object;
  - it is a closed startup record, every nested object closed as
    `check_evidence` closes it, passing by every affirmative fact the lane
    records, with strict booleans and integer zeros;
  - the artifacts it names are this host's `codex_lane.launch_facts`, the same
    producer the lane writes them with, so an older qualification cannot vouch
    for changed artifacts.
- **The conformance revisions from `Q` (S3-2).**
- **Two state paths, both service-owned under one short directory:** a bare
  `closure.git` (the closure authority) and `acquisitions`. The host-session
  runbook creates them. Before the closure authority, which installs hooks,
  is built, `closure.git` must be a directory whose path resolves to itself:
  no link anywhere, its own included, and never relative. The
  native egress socket path under it is bounded to 107 bytes, which the
  provider enforces.
- **A Linux-only guard.**

The provider stays unavailable. Its published reasons are untouched, and only an
owner's authorization admits a run.

**Host commands** (`python -m constructicon.api.qualification`):
- **`mint`** prints a no-dispatch authorization's pins, computed from this
  host's assembled provider: revision, binding digest, the fixed graph, run,
  journal and a bounded window (`--hours` 1, 2, 4 or 8). Minting is computation,
  not authority. Root reviews the record and installs it.
- **`run`** reads the installed authorization through the root-file reader,
  assembles the production provider, and runs the entry. It prints only the
  status.

Run as `python -m`, the module executes as `__main__`, and a node named
`__main__.qualification_node` cannot be imported cold by the registry. The
entry hands over to the imported module, so `mint` and `run` hash and register
the same graph.

This closes Stage 1's "no production assembly" boundary.

**Not in `PROOF_MODULES`.** R19's module list is frozen text that a test holds
equal to `PROOF_MODULES`, so the new modules do not join it. They live in the
same controller tree, which R19's import check covers.

**Proof.**
- **Portable:**
  - the sealed-account loader accepts the sealed record and refuses one the
    generation did not seal;
  - it refuses, one check at a time, a sealed record that is not closed, not
    passing, or names other artifacts;
  - it refuses duplicate keys, non-objects, empty and oversized files, and a
    FIFO without blocking;
  - the READ profile admits the READ grants and the production configuration;
  - the module entry hands over to the importable module.
- **Provisioned Linux lane, as the service:** the provider assembled from the
  real runtime, vendor and catalog with a synthetic generation (construction
  reads no store) whose evidence names this host's launch facts. It is
  unavailable, and has the READ profile, the sealed account and `Q` as each
  revision. A non-production configuration is refused, and so are an
  unprepared state and a link to the state or from `closure.git`, with
  nothing behind them touched. `mint` prints this host's pins, and the
  documented `python -m` entry mints the same graph.
- **Mutants:** twenty-one in `check_m8_n5_host_mutations.py`, one per check. The
  account's well-formedness has none, because the returned seal validates it
  again.
- **Review:** Astra (job_95d1f6760f0b) found the subset check, the `__main__`
  graph, the fixture's documentation-space addresses and long state path, the
  unbounded read, and the authority built before validation. The connector
  review found open nested shapes, permissive booleans and a linked
  `closure.git`. All are fixed.

## Part B: the read stage (next PR)

The design is as reviewed, with Fable's deltas:
- the two-phase record (S3-1);
- a `turn_written` fact, set after the write returns, so an input-budget refusal
  after intent is proven not dispatched;
- a `before_turn` callback that returns a refusal and never raises, because the
  conversation does not hold the handle;
- the loader re-running the checks (done in part A);
- bounded dispatch facts in the completed record;
- the task literal inside the node (S3-3);
- the law cited as ADR 0021:122-124 ("No exactly-once model computation or
  charge is claimed"), not I13, for why a turn is leased computation and not an
  effect.
