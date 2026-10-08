# M8 N5 Stage 3: the one READ turn

Status:
- **Part A, merged:** the production host assembly and the host commands.
- **Part B (this PR), implemented:** the read authorization, the attempt
  record, gated dispatch, the read graph and the session runbook
  (`M8-N5-read-session.md`).

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

## Part B: the read stage

A turn is leased computation, not an effect: ADR 0021:122-124 claims no
exactly-once model computation or charge. So the turn is not journaled as an
effect. One record per authorization accounts for it instead (S3-1).

**The read authorization** (`core/qualification.py`). The stage
`qualification-read` pins three more things than Stage 1's:
- the grants, which acquisition requires exactly;
- the attempt record's path, which the entry requires to be absolute;
- exactly one epoch.

A no-dispatch authorization pins neither grants nor a record.

**The attempt record** (`substrate/executors/attempt_record.py`). Every write
creates a file exclusively, writes every byte, and makes it durable (the file,
then its directory):
1. **`acquired`.** Reserved at `acquire`, before any handle exists. A second
   acquisition, even after a journal reset, finds it and refuses.
2. **`intent`.** Written by the conversation's `before_turn`, the last word
   before `turn/start` is written. It returns a refusal and never raises,
   because the conversation does not hold the handle. Expiry is checked on
   both sides of the durable write, so a slow write cannot carry an expired
   authorization into the turn.
3. **The outcome,** classified from facts:
   - `not dispatched` only if the write of `turn/start` never began
     (`turn_sent`, set as the write begins, because the transport may hold
     the bytes before a drain fails or is cancelled). An input-budget refusal
     after intent is proven not dispatched;
   - otherwise `completed` only for an accepted answer, and `possibly
     dispatched` for anything else.

   The facts are Stage 3's evidence list, bounded and never text: the
   decoded answer's length, usage or "unknown", the served model or
   "unknown", the readbacks, relay counts, process facts and identities, and
   a refusal's reason. What the conversation observed is recorded whether or
   not its result was accepted. A record that never
   reaches its outcome still reads correctly: at `acquired` nothing was
   dispatched, and at `intent` the turn possibly was.

**Gated dispatch** (`codex.py`). A read authorization's handle may dispatch.
Its `execute` settles the record however the turn ends, including on
cancellation. A clean result salvaged from a failed exchange is refused, never
published as an answer; before this, any handle would have published it. Without a read authorization nothing changes: Stage 1's handles
never dispatch, and an unqualified provider is unavailable.

**The read graph** (`api/qualification.py`). The graph is one node,
`qualification_read_node`. Its task is a literal under 200 bytes, so the
node's source digest pins it (S3-3). It accepts only an accepted text answer
and returns only its length.
`mint --stage qualification-read --attempt-record PATH` pins the READ grants;
the parser requires the record for, and only for, the read stage.

**The session** (`M8-N5-read-session.md`):
- T0 to T2: the authorization, the host as Stage 2 left it, and fresh state
  under a path that fits the egress socket bound;
- T3 and T4: the service mints and root installs;
- T5: the one `run`, which passes only if the run succeeded and the record
  completed: the turn completes inside `execute`, before the run's checkpoint
  and closure;
- T6: one retry, only after a diagnosed local failure with nothing
  dispatched, under entirely new names.

**Proof.**
- **Portable:**
  - the authorization's shape and grant pin;
  - the record's phases and exclusive reservation;
  - an intent that cannot be written refuses;
  - one completed turn with the evidence fields and no answer text;
  - a spent attempt refusing a later acquisition;
  - expiry before the turn, or during the intent's write: not dispatched;
  - an input-budget refusal after intent: not dispatched;
  - a write that began and then failed: possibly dispatched;
  - a failure after the turn was sent: possibly dispatched;
  - a clean result from a failed exchange: refused;
  - a refused turn keeps its readbacks and reason;
  - short and stalled record writes;
  - the entry end to end, including a reset journal that cannot spend the turn
    again;
  - the runbook's blocks, flags and programs, run against synthetic records,
    and each attempt's expanded state.
- **Mutants:** twenty-four in `check_m8_n5_read_mutations.py`, run in the
  lifecycle lane, one per check.
- **Review:** Astra (job_18dce68827b2) found:
  - a delivered turn recorded as not dispatched;
  - a salvaged clean result published as an answer (pre-existing);
  - T5 passing a failed run;
  - short record writes;
  - expiry during the intent's write;
  - the transcript measured as the answer;
  - refused turns losing their evidence;
  - T6 keeping the first state;
  - two unjustified mutant exemptions.

  All are fixed.
