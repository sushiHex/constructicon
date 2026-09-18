# M8 subscription-mode interface screen

Status: credential-free source and documentation screen, 2026-09-18
(America/Los_Angeles). This is not implementation authority, login approval,
candidate selection, or production qualification.

Repository context: accepted [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md)
and [frozen rev 3](../milestones/M8-live-executors-rev3.md) on `main` at
`57ebcba8fe5daab640041c49e823ee352c6b0e0b`, after N1 merged.

## Result

**The pinned Codex `0.153.4` candidate does expose a supported, non-secret,
dispatched authentication-mode observation that reads live state without a
model request: `account/read`.** Existence is not the problem the earlier
preflight left behind. Two gaps stand between that operation and ADR 0021's
requirement, and neither is closed by the interface itself:

1. **The supported operation collapses five credential variants into one wire
   value.** `account/read` reports `Account::Chatgpt` for managed ChatGPT,
   externally supplied host tokens, agent identity, personal access tokens and
   provider headers alike, and both fields of that variant can be byte-identical
   between them. ADR 0021 selects managed ChatGPT authentication and excludes
   externally supplied tokens, so this operation alone cannot separate the
   permitted mode from a forbidden one.
2. **A token refresh can move a session between credential variants with no
   notification.** The refresh path reloads credentials from disk guarded by
   account-id equality only, not by variant, and the account-updated
   notification is emitted from login and logout paths alone.

The one operation that does report the precise variant, `getAuthStatus`, is
deprecated in source **in favour of the very operation above**, and is
deliberately excluded from the vendor's generated JSON schema. It must not
become the boundary.

Both gaps are closable by construction rather than by the wire, using
mechanisms ADR 0021 already mandates: a fixed environment and configuration
that make the other variants unreachable, one operator-provisioned narrow store
that cannot present another variant, and the fresh reads the ADR already
requires before each model turn and before accepting each result. That
conversion is an interpretation of "establish", and it is the decision this
screen puts to the owner; see **Decision requested**.

## Pins and evidence boundary

Release tag `rust-v0.153.4`, source commit
[`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`](https://github.com/openai/codex/tree/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a),
the retained fixture every existing M8 proof pins. No candidate was selected,
upgraded or surveyed; no candidate-upgrade loop was started.

Two corpora were read independently and compared: the pinned source over the
GitHub API, and the published vendor documentation. No Codex login, account,
installed-binary execution, model call, vendor patching, or auth-cache or token
parsing was involved. The GitHub CLI used its existing GitHub authentication.

Vendor documentation describes the current product, not this pin, and ADR 0021
already treats those pages as interface direction only. Where the two corpora
agree, it is noted; the pinned source governs.

## The conjunction

Availability requires all seven predicates. Each was answered independently
against the pinned source.

| # | Predicate | `account/read` | `getAuthStatus` |
| --- | --- | --- | --- |
| P1 | A mode fact exists | holds | holds |
| P2 | Registered and dispatched | holds | holds |
| P3 | Obtainable without a secret | holds | holds |
| P4 | Reads live state, not startup state | holds | holds |
| P5 | Refresh cannot switch mode unobserved | **fails** | **fails** |
| P6 | Callable with no model request | holds | holds |
| P7 | Supported, not deprecated | holds | **fails** |

## Findings

### P1 — the mode fact is a first-class wire enum

`AuthMode` is defined in the app-server protocol with eight variants including
`ApiKey`, `Chatgpt`, `ChatgptAuthTokens`, `AgentIdentity` and
`PersonalAccessToken`
([`common.rs` 21-62](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/common.rs#L21-L62)).
Its domain twin carries a classifier, `has_chatgpt_account`, which returns true
for `Chatgpt`, `ChatgptAuthTokens` and `PersonalAccessToken` together
([`auth.rs` 40-63](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/protocol/src/auth.rs#L40-L63)).
That classifier is therefore unusable as a subscription test on its own.

### P2 — two callable operations, and one declared-but-dead type

`account/read` is registered
([`common.rs` 1368-1372](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/common.rs#L1368-L1372)),
dispatched
([`message_processor.rs` 1589-1591](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/message_processor.rs#L1589-L1591)),
and present in both the TypeScript and JSON method inventories.

`getAuthStatus` is registered and dispatched
([`common.rs` 1385-1390](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/common.rs#L1385-L1390),
[`message_processor.rs` 1592-1594](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/message_processor.rs#L1592-L1594))
but is excluded from the generated JSON schema by an explicit v1 method list
([`export.rs` 66-67](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/export.rs#L66-L67)).

The `AccountSession` types remain declared with no method returning them
([`v2/account.rs` 191-261](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/account.rs#L191-L261)),
reproducing the 2026-09-11 preflight's result. A declared response-shaped type
is still not a supported callable interface.

### P3 — neither operation requires a secret

`account/read` returns only `account` and `requires_openai_auth`; it has no
token field to decline
([`v2/account.rs` 534-540](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/account.rs#L534-L540)).
`getAuthStatus` can return a bearer token, but the parameter is opt-in and
declining is the default
([`v1.rs` 184-206](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v1.rs#L184-L206)).

A managed ChatGPT account response carries an email address and a plan type.
Those are not secrets, but they are account facts: ADR 0021 keeps them out of
public identity, launch identity, the journal and logs, so the adapter may
read the mode and must discard the rest.

### P4 — both read live state

Both handlers consult the auth manager at call time and reload configuration,
rather than a value captured at initialization
([`account_processor.rs` 1034-1129](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/account_processor.rs#L1034-L1129)).
The value read is a process-global mutable cache, which is what makes P5 the
live question rather than freshness.

### P5 — a refresh can change the variant, unobserved

Refreshing cannot itself move a session between variants: the refresh arm
handles managed ChatGPT and returns unchanged for every other variant
([`manager.rs` 2817-2860](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L2817-L2860)).
But refresh first reloads whatever is on disk and replaces the cached
credentials, guarded by account-id equality only and not by variant
([`manager.rs` 2764-2802](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L2764-L2802)).
That replacement emits no app-server notification.

The account-updated notification does carry the precise variant, fed by the
exact accessor
([`account_processor.rs` 200-209](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/account_processor.rs#L200-L209)),
but it is emitted from three places only, all login and logout paths. Nothing
emits it on a schedule or per turn, so its silence is not evidence. ADR 0021
anticipated this by requiring fresh reads rather than notifications; the
residual it does not cover is a change that occurs and reverts inside one turn,
which bracketing reads cannot see.

### P6 — no model request is needed

Both are reachable once the session is initialized, before any thread, turn or
model request
([`message_processor.rs` 892-901](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/message_processor.rs#L892-L901)).
This satisfies rev 3's requirement that the mode interface support a
no-model-request initialization phase.

### P7 — the precise carrier is the deprecated one

`getAuthStatus` sits under a `DEPRECATED APIs below` header and is marked
`DEPRECATED in favor of GetAccount`
([`common.rs` 1374-1390](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/common.rs#L1374-L1390)).
There is no `#[deprecated]` attribute; the markers are those doc comments plus
the schema exclusion. The named successor is `account/read` itself, so the
vendor's own direction points at the collapsing operation.

### The collapse, exactly

`account/read` does not consult either mode accessor. It matches credential
variants directly, mapping managed ChatGPT, external host tokens, provider
headers, agent identity and personal access tokens onto one account shape
([`provider.rs` 401-442](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/model-provider/src/provider.rs#L401-L442)),
converted to the wire variant
([`v2/account.rs` 46-58](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/account.rs#L46-L58)).
Its two fields are read through the same fallthrough branch for managed and
external-token sessions
([`manager.rs` 611-652](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L611-L652)),
so both can be identical. By contrast `getAuthStatus` feeds the accessor
described in source as the precise kind of credentials
([`account_processor.rs` 1065](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/account_processor.rs#L1065),
[`manager.rs` 479-506](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L479-L506)).

### Documentation agreement

The published documentation independently describes `account/read` with the
same response shape, an `account/updated` notification whose `authMode` field
is "emitted whenever auth mode changes", and a `refreshToken` parameter that
can be set false. It attaches no deprecation language to the account surface.
Two cautions it adds, which the source does not express: the app-server command
and its WebSocket transport are described as "experimental and aren't supported
for production workloads", and integrators automating jobs or running in CI are
directed to the Codex SDK instead. Those bear on how much "supported" is worth
here, and are recorded rather than resolved.

Documentation quotes were extracted from raw page source. The summarizing
fetch tool produced quote-marked text absent from those pages and missed the
account surface entirely, so its output was discarded.

## Decision requested

Neither gap is a missing interface; both are questions about what may close
one. The proposed reading is that ADR 0021's fixed environment, configuration
and startup already exclude every collapsed variant by construction — external
tokens require the host to supply them and opt into an experimental capability,
agent identity is selected by process environment, personal access tokens come
from configuration — so a `Chatgpt` reading becomes unambiguous for a sealed
profile, and the store discipline plus bracketing reads bound the refresh
swap.

Against that reading: ADR 0021 says no inferred field may stand in for these
facts, and "the other variants are unreachable, therefore this one is managed"
is an inference resting on configuration rather than an observation of the
fact itself. Whether that satisfies "establish subscription mode" is the
owner's call, because it sets how strong the word **establish** is for every
later provider.

- **If accepted**, N2 proceeds naming `account/read` as its interface, and two
  obligations move into N3 and N4: prove the forbidden variants are
  mechanically unreachable under the sealed configuration and environment, and
  prove the operator store cannot present a different variant under refresh.
  `getAuthStatus` may corroborate during qualification and must never be the
  boundary, being deprecated in favour of the operation actually used.
- **If refused**, the pinned candidate cannot establish subscription mode, the
  Codex adapter remains unavailable on this fixture, and the choice returns to
  [#38](https://github.com/sushiHex/constructicon/issues/38): authorize an
  assessment of a different release with full requalification, or reorder the
  providers.

No later release was surveyed, so nothing here suggests an upgrade. Selecting a
changed binary would repeat the catalog, startup, mediation and lifecycle
requalification rev 3 requires.

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
gh api -H "Accept: application/vnd.github.raw+json" "repos/openai/codex/contents/codex-rs/app-server-protocol/src/export.rs?ref=3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
```
