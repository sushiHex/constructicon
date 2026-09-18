# M8 subscription-mode interface screen

Status: credential-free source and documentation screen, 2026-09-18
(America/Los_Angeles). This is not implementation authority, login approval,
candidate selection, or production qualification.

Repository context: accepted [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md)
and [frozen rev 3](../milestones/M8-live-executors-rev3.md) on `main` at
`57ebcba8fe5daab640041c49e823ee352c6b0e0b`, after N1 merged.

## Result

**No supported interface in the pinned Codex `0.153.4` candidate can establish
subscription mode. N2's adapter cannot qualify on this fixture unless the owner
accepts a deprecated operation as the carrier of a credential boundary.**

Existence was never the missing piece. The pinned release registers and
dispatches `account/read`: supported, undeprecated, carrying no secret,
reading live state, reachable with no model request. It fails for a different
reason. It **collapses four credential variants** — managed ChatGPT,
externally supplied host tokens, agent identity and personal access tokens —
onto one account shape, and for the pair that matters most the two fields it
carries can be identical. It therefore reports that a session is a ChatGPT
account without saying which kind, which is precisely the distinction ADR 0021
turns on.

The obvious repair does not work. Three of those four variants can be selected
by **fields inside the credential store itself**, which ADR 0021 forbids the
adapter to read and licenses the vendor to rewrite during refresh. Sealing the
environment and the configuration, which the ADR already requires, does not
reach them. The one configuration knob that appears to help admits all four.

One operation does name the variant exactly: `getAuthStatus` reports all four
as distinct wire values. It is marked deprecated **in favour of the collapsing
operation**, and is deliberately excluded from the vendor's generated JSON
schema. Whether such a carrier may hold this boundary is the single question
this screen puts to the owner; see **Decision requested**.

## Pins and evidence boundary

Release tag `rust-v0.153.4`, source commit
[`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`](https://github.com/openai/codex/tree/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a),
the retained fixture every existing M8 proof pins. No candidate was selected,
upgraded or surveyed; no candidate-upgrade loop was started.

Two corpora were read independently: the pinned source over the GitHub API, and
the published vendor documentation. No Codex login, account, installed-binary
execution, model call, vendor patching, or auth-cache or token parsing was
involved. The GitHub CLI used its existing GitHub authentication.

Vendor documentation describes the current product, not this pin, and ADR 0021
already treats those pages as interface direction only. The pinned source
governs; documentation agreement is noted where it exists.

Every citation below was independently re-verified against the pinned source by
a second reader, which corrected one miscount and one wrong claim in an earlier
draft of this record.

## The conjunction

Availability needs all eight predicates from one carrier. **No carrier supplies
all eight**, and the two candidates fail on disjoint predicates.

| # | Predicate | `account/read` | `getAuthStatus` |
| --- | --- | --- | --- |
| P1 | A mode fact exists | holds | holds |
| P2 | Registered and dispatched | holds | holds |
| P3 | Obtainable without a secret | holds | holds |
| P4 | Reads live state, not startup state | holds, cache only | holds, reloads |
| P5 | Refresh cannot switch mode unobserved | **fails** | **fails** |
| P6 | Callable with no model request | holds | holds |
| P7 | Supported, not deprecated | holds, transport caveat | **fails** |
| P8 | Names the permitted variant distinctly | **fails** | holds |

P8 is the predicate the original scope missed. A mode fact can exist, be
dispatched, be secret-free, be live and still fail to say which kind of ChatGPT
credential is in use, which is exactly what happens here.

The deprecated operation is the stronger carrier on every axis but one. It
names the variant, and it is also the fresher of the two: it reloads and can
proactively refresh, while the supported operation reads a cache without
reloading. It loses only P7 — which is the axis the vendor controls, and the
reason this record does not recommend it.

## Findings

### P1 — the mode fact is a first-class wire enum

`AuthMode` carries eight variants including `ApiKey`, `Chatgpt`,
`ChatgptAuthTokens`, `AgentIdentity` and `PersonalAccessToken`
([`common.rs` 21-62](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/common.rs#L21-L62)).
Its domain twin's `has_chatgpt_account` classifier returns true for `Chatgpt`,
`ChatgptAuthTokens` and `PersonalAccessToken` together
([`auth.rs` 40-64](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/protocol/src/auth.rs#L40-L64)),
so it is unusable as a subscription test.

### P2 — two callable operations, and one declared-but-dead type

`account/read` is registered
([`common.rs` 1368-1372](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/common.rs#L1368-L1372))
and dispatched
([`message_processor.rs` 1589-1591](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/message_processor.rs#L1589-L1591)),
and appears in both generated inventories.

`getAuthStatus` is registered and dispatched
([`common.rs` 1385-1390](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/common.rs#L1385-L1390),
[`message_processor.rs` 1592-1594](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/message_processor.rs#L1592-L1594))
but is stripped from the generated JSON schema by
`strip_v1_client_request_variants_from_json_schema`
([`export.rs` 1403-1406](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/export.rs#L1403-L1406),
invoked at [1339](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/export.rs#L1339))
over the v1 method list
([`export.rs` 66-67](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/export.rs#L66-L67)).
Verified by effect: the JSON inventory contains `account/read` and no
occurrence of `getAuthStatus`; the TypeScript inventory contains both.

The `AccountSession` types remain declared with no method returning them
([`v2/account.rs` 233-243](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/account.rs#L233-L243)),
reproducing the 2026-09-11 preflight's result.

### P3 — neither operation requires a secret

`account/read` returns only `account` and `requires_openai_auth`, with no token
field to decline
([`v2/account.rs` 534-540](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/account.rs#L534-L540)).
`getAuthStatus` can return a bearer token, but the parameter is opt-in and
declining is the default
([`v1.rs` 184-206](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v1.rs#L184-L206),
[`account_processor.rs` 1038](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/account_processor.rs#L1038)).

A managed ChatGPT response carries an email address and a plan type. Not
secrets, but account facts ADR 0021 keeps out of public identity, launch
identity, the journal and logs: read the mode, discard the rest.

### P4 — both read live state, but not equally

Neither uses a startup snapshot
([`account_processor.rs` 1034-1129](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/account_processor.rs#L1034-L1129)),
but they differ in a way that matters. `account/read` reads the cached
credentials only, never reloading and never proactively refreshing
([`provider.rs` 406](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/model-provider/src/provider.rs#L406)).
`getAuthStatus` goes through the awaiting accessor, which reloads under
external auth and can refresh proactively
([`account_processor.rs` 1059](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/account_processor.rs#L1059),
[`manager.rs` 2345-2359](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L2345-L2359)).
The supported operation is therefore the less fresh of the two: after an
on-disk change it can keep reporting the cached mode until something else
reloads. The value both read is a process-global mutable cache, which makes P5
rather than freshness the live question.

The handlers are also not symmetric: `getAuthStatus`
reports `Chatgpt` and `ChatgptAuthTokens` *through* a token fetch, so an empty
or failing token yields no mode at all
([1084-1088](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/account_processor.rs#L1084-L1088)),
while `AgentIdentity` and `PersonalAccessToken` bypass that path and always
report
([1066-1077](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/account_processor.rs#L1066-L1077)).
The permitted variant is the one that can go silent; the forbidden ones cannot.
Both fail closed, and an adapter must treat absence as refusal.

### P5 — a refresh can change the variant, unobserved

Refresh reloads whatever is on disk and replaces the cached credentials,
guarded by account-id equality alone and not by variant
([`manager.rs` 2764-2802](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L2764-L2802)).
Under external auth the refresh installs whatever resolves
([2828-2830](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L2828-L2830),
[2752-2762](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L2752-L2762)),
and a separate reload path carries no account-id guard at all
([2425-2429](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L2425-L2429)),
reached on every access under external auth
([2346-2348](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L2346-L2348)).
Only the managed branch is variant-preserving
([2832-2852](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L2832-L2852)).

None of this emits a notification. The account-updated notification does carry
the precise variant
([`account_processor.rs` 200-209](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/account_processor.rs#L200-L209))
but is emitted only from login and logout paths, so its silence is not
evidence. Cached auth is additionally mutated by the plain reload, by external
commit and clear, and by managed token persistence.

### P6 — no model request is needed

Both are reachable once the session is initialized, before any thread, turn or
model request
([`message_processor.rs` 892-901](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/message_processor.rs#L892-L901)),
satisfying rev 3's no-model-request initialization requirement.

### P7 — the precise carrier is the deprecated one

`getAuthStatus` sits under `/// DEPRECATED APIs below` and is marked
`/// DEPRECATED in favor of GetAccount`
([`common.rs` 1374-1390](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/common.rs#L1374-L1390)).
There is no `#[deprecated]` attribute; the markers are those comments plus the
schema strip. `GetAccount` is `account/read`, so the vendor's own direction
points at the collapsing operation.

`account/read` carries no deprecation of its own, but its support is not
unqualified either: the vendor documents the app-server command and its
WebSocket transport as
"experimental and aren't supported for production workloads", and directs
integrators automating jobs or running in CI to the Codex SDK instead
([app-server](https://learn.chatgpt.com/codex/app-server)). That caveat covers
the surface both operations live on.

### P8 — what collapses, exactly

`account/read` consults neither mode accessor. It matches credential variants
directly, and **four** reach one account shape: `Chatgpt`, `ChatgptAuthTokens`,
`AgentIdentity`, `PersonalAccessToken`
([`provider.rs` 415-431](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/model-provider/src/provider.rs#L415-L431)),
converted to the wire variant
([`v2/account.rs` 46-58](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/account.rs#L46-L58)).
`Headers` is **not** among them: it returns early, yielding a null account
([`provider.rs` 410-412](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/model-provider/src/provider.rs#L410-L412)).

For managed ChatGPT against external host tokens the two fields are reached
through the same fallthrough branch
([`manager.rs` 611-652](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L611-L652)),
so the responses can be identical; an external host may omit the plan type,
which is its own choice, so the worst case is indistinguishable. Agent identity
and personal access tokens take different accessor branches, so they are not
byte-identical to managed ChatGPT, but they still arrive as the same
`Account::Chatgpt` variant and so are not separated by the account type either.

By contrast `getAuthStatus` feeds the accessor documented as the precise kind
of credentials
([`account_processor.rs` 1065](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/account_processor.rs#L1065),
[`manager.rs` 494-506](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L494-L506)),
and the wire conversion is a bijection over all eight variants
([`auth_mode.rs` 10-21](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/auth_mode.rs#L10-L21)).
It therefore reports all four as distinct values. The collapsing accessor's own
documentation states that externally managed tokens are normalized to the
managed value
([`manager.rs` 479-492](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L479-L492)).

### Documentation agreement

The published documentation independently describes `account/read` with the
same response shape, including the managed-ChatGPT case carrying an email and
plan type, and an `account/updated` notification whose `authMode` field is
"emitted whenever auth mode changes"
([app-server](https://learn.chatgpt.com/codex/app-server)). It names two sign-in
methods, "Sign in with ChatGPT for subscription access" and "Sign in with an API
key for usage-based access", and describes the external-token mode as
"experimental and intended for host apps that already own the user's ChatGPT
auth lifecycle"
([auth](https://learn.chatgpt.com/codex/auth)). It also states that
account-authenticated automation must not be used "for public or open-source
repositories"
([CI/CD auth](https://learn.chatgpt.com/codex/auth/ci-cd-auth)), consistent
with ADR 0019's credential-free Actions posture.

Nothing in the documentation describes the collapse, the store-resident variant
selectors, or the account-id-only reload. Those are source facts with no
documented counterpart, which is why the pinned source governs here.

## Why exclusion by construction fails

An earlier draft of this record proposed that ADR 0021's fixed environment,
configuration and startup could make the collapsed variants unreachable, so a
ChatGPT reading would be unambiguous for a sealed profile. **That reading does
not survive the source.**

- **Two variants are selected by store content.** Agent identity and personal
  access tokens each have a dedicated field in the credential file
  ([`manager.rs` 314-346](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L314-L346),
  [348-355](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L348-L355)),
  read on both the ephemeral and persistent paths
  ([1474-1476](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L1474-L1476),
  [1535-1537](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L1535-L1537)).
  ADR 0021 forbids the adapter to parse that file and permits the vendor to
  rewrite it on refresh, so neither environment nor configuration reaches them.
- **The configuration knob that looks decisive is not.** Forcing the login
  method to ChatGPT admits every backend-using mode, because the check folds
  them together
  ([`manager.rs` 1215-1224](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L1215-L1224),
  [`auth.rs` 53-63](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/protocol/src/auth.rs#L53-L63)).
  The related restriction check tests the *normalizing* accessor, so it cannot
  see external tokens at all
  ([`manager.rs` 1227-1240](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L1227-L1240)).
  No configuration value at this pin admits managed ChatGPT while refusing
  agent identity or personal access tokens.
- **The two gaps are one gap.** The refresh reload keys on an account id whose
  space is shared across managed ChatGPT, agent identity and personal access
  tokens
  ([`manager.rs` 584-596](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L584-L596)),
  so a store-resident variant is reachable mid-session, not only at startup.

Externally supplied tokens are excluded by ADR 0021's own text. Agent identity
and personal access tokens are not named there; excluding them is
Constructicon's extension of "vendor-managed subscription", and this record
treats them as excluded on that basis.

## What ADR 0021 requires, and what is missing

- "A supported, non-secret authentication-mode observation must establish
  subscription mode freshly for the executing session before each model turn
  and before accepting its result." The supported carrier collapses; the
  carrier that names the variant is deprecated.
- "Qualification must prove that vendor refresh cannot silently select
  API/cloud authentication mid-turn." Unprovable while the reload swaps on
  account id alone from a store the adapter may not read.
- "Every reachable input must be excluded, fixed and revision-bound, or
  mechanically constrained at its point of use." The credential file's variant
  fields are a reachable input that is none of those.
- "If the pinned interface cannot prove mode selection, that adapter remains
  unavailable." The disposition, absent the decision below.

## Decision requested

One question, and it is narrower than it looks. `getAuthStatus` is the only
operation at this pin that can establish the fact. It is registered,
dispatched, secret-free by default, live, callable with no model request, and
reports all four variants distinctly. It is also deprecated in favour of the
operation that hides the distinction, and stripped from the vendor's generated
schema.

**May a deprecated carrier hold a credential boundary?**

This record's recommendation is **no**. Building the subscription guarantee on
an operation the vendor has marked superseded, by the very operation that
collapses the distinction, inverts the direction the vendor is moving and makes
the guarantee fail at the moment the method is removed. ADR 0021 asks for a
*supported* observation, and this one is signposted for removal.

- **If the owner agrees**, the Codex adapter is unavailable on this fixture.
  N2 is blocked and the choice returns to
  [#38](https://github.com/sushiHex/constructicon/issues/38): authorize an
  assessment of a different release under full requalification, reorder the
  providers so Claude Code goes first, or revisit the route.
- **If the owner accepts the deprecated carrier**, N2 may proceed naming
  `getAuthStatus`, and carries three obligations: treat absence of a mode as
  refusal, since the permitted variant is the one that can go silent; prove the
  store cannot present another variant under refresh, which the store-resident
  selectors make the hard part; and record its removal as a named
  requalification trigger, because a vendor release that deletes the method
  ends availability.
- **A third reading exists and is recorded rather than recommended.** Keep
  `account/read` as the carrier and move the whole burden onto the binding:
  require N3 and N4 to prove that the operator store is provisioned only
  through the supported managed login and cannot come to hold the variant
  fields, so a ChatGPT reading is sound because of what the store is, not
  because of what the wire says. This is weaker than it looks. The adapter may
  not read the file to check, the vendor may rewrite it during refresh, and
  `account/read` reads a cache that can lag an on-disk change, so the proof
  would rest entirely on provisioning discipline and physical custody. It also
  needs the freshness gap closed some other way.

Under every reading P5 remains open, so no acceptance here qualifies the
adapter by itself.

No later release was surveyed, so nothing here suggests an upgrade. Selecting a
changed binary would repeat the catalog, startup, mediation and lifecycle
requalification rev 3 requires.

## Further questions this screen did not settle

Per-thread model provider and configuration overrides exist and are not
experimental; configuration is re-read from disk per call with a silent
fallback to startup configuration; `requiresOpenaiAuth` gates the mode report
in both operations and is not explained here; and a null account has several
distinct causes that an adapter must not conflate. Each belongs to N2 or N3 if
this route continues.

## Reproducing this screen

Public-source checks needing no Codex login or binary execution; the GitHub CLI
uses its existing GitHub authentication.

```powershell
gh api repos/openai/codex/git/ref/tags/rust-v0.153.4
gh api -H "Accept: application/vnd.github.raw+json" "repos/openai/codex/contents/codex-rs/app-server-protocol/src/protocol/common.rs?ref=3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
gh api -H "Accept: application/vnd.github.raw+json" "repos/openai/codex/contents/codex-rs/app-server-protocol/src/protocol/v2/account.rs?ref=3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
gh api -H "Accept: application/vnd.github.raw+json" "repos/openai/codex/contents/codex-rs/app-server/src/request_processors/account_processor.rs?ref=3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
gh api -H "Accept: application/vnd.github.raw+json" "repos/openai/codex/contents/codex-rs/login/src/auth/manager.rs?ref=3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
gh api -H "Accept: application/vnd.github.raw+json" "repos/openai/codex/contents/codex-rs/model-provider/src/provider.rs?ref=3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
gh api -H "Accept: application/vnd.github.raw+json" "repos/openai/codex/contents/codex-rs/protocol/src/auth.rs?ref=3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
gh api -H "Accept: application/vnd.github.raw+json" "repos/openai/codex/contents/codex-rs/app-server-protocol/src/export.rs?ref=3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
```

The documentation quotes were taken from raw page source, not from a
summarizing fetch tool, which on this material produced quote-marked text
absent from the pages and missed the account surface entirely:

```bash
curl -sL https://learn.chatgpt.com/codex/app-server
curl -sL https://learn.chatgpt.com/codex/auth
curl -sL https://learn.chatgpt.com/codex/auth/ci-cd-auth
```
