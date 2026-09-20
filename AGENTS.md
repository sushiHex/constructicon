# Constructicon — agent contributor guide

Agents are this repository's first-class contributor. Everything you need is
four documents and one command:

- `docs/INVARIANTS.md` — the thirteen laws, the four-noun execution kernel,
  and the never list. Read first; a change that violates one is wrong even if
  it works.
- `docs/ARCHITECTURE.md` — the current truth: layers, IR, authoring contract,
  durable control plane, manifest, effects, registry, journal, milestones, and
  failure tests.
- `docs/CONTRIBUTING.md` — one page per extension kind.
- `docs/AGENT_HANDOFF.md` — what recent slices actually established, what they
  deliberately did not, and which reported facts turned out to be wrong. Read
  it when arriving cold; it is context, never a task ledger.

```bash
uv run verify        # ruff + mypy --strict + import-linter + pytest — what CI runs
```

## Work tracking

Follow `docs/WORK_TRACKING.md` when selecting, starting, handing off, or closing
work. GitHub Issues owns the backlog, dependencies, and ownership; plans and
accepted ADRs own design authority. Query current issues and linked PRs before
starting, and leave a branch/head handoff when pausing. Do not keep a second
TODO in Markdown or infer approval from an issue or `ready` label. Review and
status requests alone do not authorize external mutations.

## The map

```text
src/constructicon/
├── core/        L0 — every contract, defined once (stdlib + Pydantic only)
├── substrate/   L1 — executors, journal/control store, effects, git, gates
├── runtime/     L2 — registry, typed authoring preflight, validator → manifest,
│                     walker (imports core contracts only — never substrate)
├── sdk/         L3 — @task + component/flow/harness/loop/panel authoring sugar
└── api/         L4 — system object, ControlPlane, RunHost, cursor/detail logic,
                      optional MCP adapter, and the injection root
tests/           mirrors the layers + credential-free e2e acceptance lanes
docs/adr/        history by reference — why things are the way they are
```

## Rules that bite

- **Inspect before inventing.** Use `system.describe()` for stable components,
  schemas, capabilities, root grants, and authoring vocabulary before creating
  a primitive. Use `describe_component()` and `rdeps()` for detail and impact.
- **One Graph language.** SDK combinators and raw JSON must produce the same
  strict `Graph` and pass the same validator. No SDK AST, hidden default,
  automatic repair, or alternate workflow representation.
- **Compose before you drop a tier.** Check for an existing component or
  contract before writing a new one; new primitives need a reason.
- **The walker decides nothing.** If your change makes the walker resolve,
  search, inherit, choose, or judge safety at runtime, it belongs in admission
  or an effect adapter instead.
- **MCP is a skin.** Durable authority lives in `ControlPlane`, `ControlStore`,
  the journal, registry, and effect adapters. An MCP handler derives its actor,
  delegates once, and returns the typed result. It never opens SQLite, computes a
  `RunId`, interprets a cursor, or reconciles a command.
- **One durable command law.** Every mutation takes a caller idempotency key and
  follows `authorize → claim → plan → apply once → record → replay`. Add fault
  tests after plan commit, after domain mutation, and after command completion.
- **One RunId, one scheduler.** `RunHost` owns process-local worker coroutines and
  restart recovery only. It never schedules graph units; the walker remains the
  sole graph scheduler. Server shutdown abandons work without inventing user
  cancellation.
- **Counterfactual means simulated.** It pins the source world except exact,
  contract-compatible overrides. Effect adapters use a separate simulated
  identity and `simulate()`, never `execute()` or `reconcile()`; mutable
  capabilities close with `discard`.
- **Actors come from transports.** Stdio receives a trusted fixed actor; HTTP
  receives a verified OAuth actor. Never add `actor_id`, `user`, or similar
  caller-controlled identity fields to tools.
- **Registration never propagates.** Only promotion moves a pointer, and only
  with a journal-minted attestation whose baseline still equals current stable.
- **Truthful telemetry and contracts.** `None` over inferred; partial over
  dropped; legacy opaque over invented completeness; simulated over false
  committed; demoted over false-ok.
- **No credentials in tests.** The full lifecycle runs fake-first; recorded
  transcripts test drivers. MCP tests use the official in-memory client and a
  fake token verifier where HTTP identity matters.
- **Frozen decisions stay frozen.** The never list and ADRs are not reopened
  because an implementation detail feels inconvenient — make the implementation
  satisfy the invariant.
- **Frozen bytes stay frozen too.** An accepted plan was accepted *as written*,
  so its bytes are the approved artifact, not a description of one. Current
  status lives in `docs/plans/README.md` and the living implementation record;
  preserved pre-decision wording inside a plan is history, not a stale status
  to correct. Editing it destroys the thing that was approved.

## What the gate does not cover

`uv run verify` is ruff, mypy, import-linter and pytest. Everything below is
real and passes a green gate, so it is yours to check by hand.

- **`docs/plans/MANIFEST.sha256` is unchecked.** Change any document under
  `docs/plans/` and refresh its digest in the same commit, then verify all of
  them with `sha256sum --check MANIFEST.sha256` from that directory.
- **`scripts/` is outside every step.** mypy covers `src/constructicon`, ruff
  covers `src` and `tests`, pytest's testpaths is `tests`. Running a mutation
  inventory is its only validation.
- **Workflows never execute locally.** A change to `.github/workflows/` is
  tested only by CI, so the PR's own run is the first execution.
- **Never `ruff format` a pre-existing file.** The repository is not
  format-clean and the gate runs `ruff check` only; a format pass drags
  unrelated reflows into the diff.
- **Set `PYTHONIOENCODING=utf-8`** or import-linter falsely reports FAILED
  under cp1252 on Windows.

## Evidence

The recurring failure in this repository is not a wrong answer; it is an
absence of evidence read as a positive result. Each rule below was bought.

- **A negative inference is not a positive fact.** An empty fault list can mean
  "the check passed" *and* "the code died before recording anything". An id
  match can mean "this is the reply" *and* "something guessed the id". Record
  the fact affirmatively, or write the limit down and pin it with an assertion.
- **A test that never ran is not evidence**, exactly as an unmeasured mutant is
  not a kill. Report written-but-unexecuted work as unverified, and prefer
  substituting only the platform-bound primitive so the test actually runs.
- **A mutant that errors is not a kill.** `scripts/_mutations.py` requires an
  assertion failure and reports NOT PROVEN otherwise, correctly. Sharpen the
  test rather than dropping the mutant. It also dedents the target's source, so
  a multi-line replacement is written at four spaces.
- **A bound needs an input where the bound binds**, or its mutant survives
  against a case too small to reach it.
- **Test the accepting path from the first commit.** A suite whose checks all
  drive a refusal proves nothing about what it permits, and the permitting path
  is where real data is published.
- **Review what state exists when each `await` resumes** — before implementing,
  not after. Something buffered, latched or aborted between two steps, which a
  later step assumes cannot be there, is the defect class that survives both a
  green gate and a full inventory.
- **Bound public surfaces by invariant, not site by site.** Walk every field of
  the published outcome and assert each against its declared bound; a rule
  fails when a *new* site appears, a site-by-site fix only after someone finds
  it.

## Review

- **A review is a claim.** Reproduce its premise against source before acting.
  Premises here have been false, and one correct-sounding finding would have
  removed a live guard.
- **Classify every finding** as introduced, pre-existing, or a design choice you
  disagree with. Only the first two block. **Record what you reject and why**,
  beside what you adopt, or it gets re-litigated.
- **Expect a defect inside the fix.** Every review round on N2 found one in the
  previous round's fix — four for four. A narrow follow-up pass attacking only
  the newest change is cheap and has paid for itself every time.
- **Read the PR conversation, review comments and reviews before marking ready
  or merging.** Unaddressed comments block. "One instance found" and "one
  instance exists" are different claims: check the class, not the report.
