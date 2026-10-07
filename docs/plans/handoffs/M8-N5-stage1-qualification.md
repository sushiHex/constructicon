# M8 N5 Stage 1: the qualification acquisition

Status: design, for one independent review before it is built.
Credential-free: no vendor client runs and no model is called.
Scope: Stage 1 of [M8-N5-state-review.md](M8-N5-state-review.md) (frozen;
lines 95-99): "a narrow entry that runs the real acquire, record, enroll,
materialize, cancel, close and reconcile implementation. It never makes the
provider available and clears no unearned reason. It needs the bounded
qualification authorization to run. Deterministic fault tests: lease
recording, cancellation, loss of ownership, joined cleanup and recovery."
Authority:
- [ADR 0020](../../adr/0020-native-harnesses-mediate-contained-tools.md),
  lines 407-412: qualification runs "through the same owned
  launcher/driver/worker and lease boundaries", never advertising a production
  provider as available or fabricating conformance. The harness gathers its
  evidence "without a public availability override, caller-selectable bypass,
  or second lifecycle owner".
- [ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md)
  and [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md),
  unchanged.

## The conflict, and why both gates stay

The seven steps already exist and run in production for the Git providers:

| Step | Walker or journal | Codex provider |
|---|---|---|
| acquire | `walker.py:1119-1127` | `codex.py:2117-2136` |
| record | `walker.py:1128-1148`, `_sqlite_execution.py:645-720` | |
| enroll | `walker.py:1609` | |
| materialize | `walker.py:1610` | `codex.py:1516-1560` |
| cancel | `walker.py:400-412`, `:1697-1701` | `codex.py:1478-1486` |
| close | `walker.py:1050-1097` | `codex.py:2138-2163`, `:1885-1940` |
| reconcile | `walker.py:1151-1201` | `codex.py:2165-2198` |

No production assembly builds the Codex provider. Two gates refuse an
unavailable one:

- admission (`validator.py:892-900`, through `registry.py:158-169`);
- `acquire` (`codex.py:2118`).

Its published reasons (`codex.py:210-223`) include egress, which Stage 1 cannot
earn: model-session egress is N5's later work. "Runs the real acquire" and
"never makes the provider available" therefore cannot both hold as the code
stands.

Teaching both gates an authorization exception (the map's option A) would
reach into the runtime layer. It would also make the production provider's
availability depend on what it was handed. This design keeps both gates, and
every published reason, exactly as they are.

## Design

**A qualifying provider, a separate object that cannot dispatch.**
`CodexOperatorProvider.qualifying(authorization, ...)` constructs the provider
with the real binding store, closure and acquisition root.

- **It is available inside its private assembly only.** That is honest,
  because it can do nothing the reasons guard against: `execute` always
  refuses ("a qualification acquisition dispatches no turn"), so no vendor
  client, egress or credential use can follow from it.
- **It differs from the production provider in exactly two facts:** its
  reasons are empty, and `execute` refuses. Its identity and launch identity
  are the production ones.
- **The production provider is never touched.** Its constructor, reasons and
  gates are unchanged.

**The authorization is the only way in.** `QualificationAuthorization` lives in
its own module, and an import-linter contract confines that module to the
qualification entry and the provider. No production assembly can import it.
It is built only from a record the owner reviewed, matched by digest, that
names:

- the stage;
- the sealed binding (`operator_binding_digest`);
- the run's idempotency key;
- a count of one acquisition.

A mismatched or reused record refuses before anything is acquired.

**The entry.** `python -m constructicon.api.codex_qualification` lives in the
api layer (import-linter: `pyproject.toml:65-74`):

- It builds a private `Constructicon` over a private SQLite journal with
  exactly one component, which declares the leased executor capability and
  never calls it.
- It starts one run through `ControlPlane`, so the walker owns every
  transition. Then a second interpreter recovers it.
- It writes closed evidence (`EvidenceFile`): the lease rows, closure refs and
  dispositions; the production assembly's reasons, recomputed and unchanged;
  `production_available: false`; `vendor_conformance_qualified: false`.

**It never:**
- launches the vendor client or calls `execute`;
- reads the credential (materialize opens and checks the store binding and
  lock, never the file's content);
- clears or narrows a published reason;
- writes a conformance revision;
- adds a flag, an MCP tool or a public assembly path;
- records a lease outside the walker;
- reuses an acquisition.

## Proof

Portable, through the walker with SQLite, the real provider, `StoreWorld` and
the portable guard (the pattern in `test_codex_write_lifecycle.py:274-297`).
The accepting path comes first:

1. **Accepting path.** Acquire, record, enroll, materialize (store lock held,
   binding checked), release, close. The rows, the closure ref and the
   disposition are asserted from SQLite.
2. **Lease recording.**
   - A failure at `lease.after_record_commit`: the handle is discarded and the
     row reconciled.
   - `OwnershipLost` at record: discarded unrecorded.
3. **Cancellation:** while the store lock is held by maintenance; after
   materialization; during close.
4. **Loss of ownership:** mid-materialization, with the row left to the
   successor.
5. **Joined cleanup:** a cleanup failure is preserved through `_finish_cleanup`.
6. **Recovery:** a successor interpreter reconciles at each phase, with the
   closure committed and the store intact.
7. **Refusals:**
   - no authorization, or a mismatched or reused one;
   - `execute` on the qualifying provider;
   - the production assembly's `describe()` and admission unchanged, still
     refusing.

Every fault point asserts its probe fired. A Linux twin repeats the accepting
path and one successor recovery with the real acquisition guard and store
lock. Mutants cover:

- `execute`'s refusal;
- the authorization check and its single use;
- the qualifying reasons staying out of production;
- each fault test's assertion.

## Open for the owner

**What "the bounded qualification authorization" is.** The plan names it but
defines it nowhere (`M8-N5-state-review.md:98` is its only occurrence).

- **Recommended:** a short record the owner approves in the PR that adds it,
  `docs/plans/authorizations/n5-stage1.json`, naming the stage, the binding
  digest and one acquisition, whose digest the entry checks.
- **Running it on the host** stays a separate owner action, as every stage's
  run does. The CI tests use a fixture record and never claim the
  authorization.
