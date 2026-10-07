# M8 N5: the sealed account identity

Status: design, independently reviewed once (Codex `gpt-6-sol`, job
`job_80d69b31fa35`) and amended; see [Review disposition](#review-disposition).
Implemented; results in the
[M8 implementation record](M8-implementation-record.md#n5-the-sealed-account-identity).
Credential-free. Nothing here contacts OpenAI or makes the provider available.
Scope: the gap #127 recorded
([M8-N5-account-read-recovery.md](M8-N5-account-read-recovery.md), "Review of
the diff"). `ExpectedAccount` binds the account type and plan, not the
account. The vendor's own check protects one in-flight discovery only, so a
switch completed before the adapter's reading would present another `pro`
login as a clean reading.
Authority: [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md),
unchanged. The evidence rule stands: evidence never records an email or an
account id.

## Findings at the pin

`account/read`'s reply names the account by two facts, and nothing else on
the wire does (`app-server-protocol/src/protocol/v2/account.rs` at
rust-v0.160.1):

- `account.email`, the login (`:29-36`). The wire type allows null.
- `workspaceRouting.chatgptAccountId`, the workspace (`:557-571`). It is the
  `tokens.account_id` the backend check was sent for, and is absent when
  discovery did not run.

The vendor's internal user id, which its own account-switch check compares
(`login/src/auth/change_state.rs:15-30`), never reaches the wire. So this
binds **the account as the wire names it**: one login in one workspace. It
catches a different login or a different workspace in the store, which is
the realistic switch. It cannot see a change only the vendor's hidden user id
would show.

## Design

**The identity.** `account_identity(reply)` is
`digest("codex-account-identity", 1, {"email", "workspace"})` over the two
facts, or `None` when either is absent or empty. Neither value is kept.
Reversing the digest means guessing both the email and the workspace id. It
is deterministic, so repeated seals of one account are equal by design, which
is what continuity compares.

**The expectation.** `ExpectedAccount` gains `identity: Digest | None`.
`account_faults` judges it only when the reading names an account, because
`NO_ACCOUNT_FAULT` already refuses the rest:

- a reading whose account has no identity is refused ("the reading names no
  login and workspace to bind"), fail-closed. Whether a paid login ever
  shows a null email is unverified; the owner's S4 qualification would
  surface it as this refusal;
- a reading whose identity differs from a sealed one is refused ("the
  account is not the one this binding sealed").

`identity: None` exists for qualification alone, as `alternatives` does. Its
first reading's identity is sealed for the run, beside its plan
(`codex.py:1252-1258`), so the after-turn reading (`:1329-1335`) must name the
same account. This is trust on first use of the owner's own attended login,
which is the root of trust that S3 and S4 already have.
`CodexOperatorProvider` refuses an expectation without an identity.

**The evidence.** The lane's `gate` gains `account`: the identity of the
first reading, recorded even when that reading is refused, so S6c's evidence
still shows the account it judged. `LANE_SCHEMA` becomes 4.

**One sealed token.** The runbook carries the expectation as one value from
qualification evidence to every later check, and it stays one value.

- `ExpectedAccount.seal` renders `<plan>/<identity>`, and
  `ExpectedAccount.from_seal` parses exactly that grammar: one slash, a known
  plan literal, a canonical digest.
- The lane's `--expected` takes the token.
- `check_evidence` compares the plan and the account with it, and accepts `-`
  only for the first qualification and a login.
- The runbook's `read_plan` becomes `read_seal`, and `PLAN` and `S4_PLAN`
  become `SEAL` and `S4_SEAL`, through S6a, S6b, S6c, S8, S9 and S10.
- S6c sends the observed identity with the wrong plan, so its plan fault is
  the only one.

**The production binding, stated rather than built.** Publish seals the
qualification evidence's digest into the generation
(`operator_store.py:1611-1629`). Production assembly does not exist yet. When
Stage 3 builds it, it must take the seal from that same evidence, after
checking its digest against the generation, and never from a caller. Until
then, the provider's refusal of an unsealed expectation is the only
production-side guard.

## Proof

- **Portable:**
  - `account_identity` over each missing, empty and differing fact;
  - both refusals in `account_faults`;
  - the seal's round trip, and its refusal of every malformed token;
  - the provider's refusal of an unsealed expectation;
  - the adapter sealing its first reading and refusing an after-turn reading
    that names another account;
  - the checker on `gate.account`, the seal, and the `-` rule.
- **On the real binary,** in #127's recovery lane:
  - the clean case runs with the fixture's sealed identity and is accepted;
  - a new `stranger` case runs the same clean recovery against another
    login's sealed identity, and our identity fault refuses it at
    `account/read`. That is the operational switch: the binding was sealed
    for one login, and the store now holds another.
- **Mutants:** each refusal, the seal's parse, the per-run sealing, and the
  gate record.

## Review disposition

One Codex pass (`gpt-6-sol`, job `job_80d69b31fa35`) on the draft.

Adopted:
- **The identity is the wire's, not the vendor's user id.** #127's fixture
  varies only that hidden id, so `stranger` uses another login's email. The
  design now says what the pin can and cannot see.
- **A null email is a legal wire shape.** It is kept as a fail-closed
  refusal, recorded as unverified for paid logins.
- **"Cannot be reversed" was unconditional.** It now states its premise.
- **`account/updated` cannot show a same-plan switch.** It has no identity
  fields, so the two readings remain the comparison points.
- **The checker's `-`** is confined to the first qualification and logins.
- **S6c's identity:** `gate.account` is recorded even for a refused reading.
- **Seal propagation** through every runbook site.
- **The production binding** is stated as Stage 3's requirement.
- **Trust on first use** is named, not implied.

Rejected:
- **Sampling between readings.** A switch between the two readings that
  switches back is invisible to any wire check. The readings bracket every
  turn, and that bracket is the contract.
