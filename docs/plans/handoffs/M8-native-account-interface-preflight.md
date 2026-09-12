# M8 native account interface preflight

Status: credential-free source/schema investigation result, 2026-09-11
(America/Los_Angeles). This is not ADR acceptance, implementation authority,
login approval, or production qualification.

Repository context: proposed ADR 0020 and M8 rev 2 at
`b930064e7ac787f3e46ca3cb9c3294e400d2978b`, rebased on main
`e796394369a2db7a4090bf56b58d24a27f290768`.

## Result

**The pinned Codex `0.153.4` candidate is not viable for ADR 0020's account
authority law. N1 must not start.** Its supported app-server surface has no
non-secret response, or supported combination of responses, that supplies both
a stable principal and the current value of each independently selectable
workspace, tenant or organization scope. Richer account-session records are
declared in source, but no method returning them is registered or dispatched.

The separate store question has a narrower result: pinned source supports one
plausible file-only layout, with `auth.json` mounted read/write at that exact
path inside a disposable `CODEX_HOME`. This is source feasibility, not an
executed Linux placement or refresh proof. It cannot cure the missing identity
interface, so the conjunction required before N1 fails.

[ADR 0020](../../adr/0020-native-harnesses-mediate-contained-tools.md) and the
[rev-2 plan](../milestones/M8-live-executors-rev2.md) remain proposed. Accepted
ADR 0018 continues to govern.

## Pins and evidence boundary

The upstream annotated tag `rust-v0.153.4` targets source commit
[`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`](https://github.com/openai/codex/tree/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a).
The retained Linux binary SHA-256 is
`56ef98ab4032d317ab26e9b5e5a175650717351edb16ed9cde0cb6d1734d62da`.

PR [#67](https://github.com/sushiHex/constructicon/pull/67)'s successful
[native run 34671838501](https://github.com/sushiHex/constructicon/actions/runs/34671838501)
retains artifact `10291726051` (`m8-containment-34671838501-1`), archive
SHA-256 `4c6b6288c3ebfe50f91fa858e8662035007a33cab4ace045d289477bc0a03e3d`.
Its `m8-service/evidence/codex-schema.json` records the binary digest, generated
schema hashes, and the generated `ClientRequest` method inventory. The binary's
`v2/GetAccountResponse.json` hash is
`08a7dd8c570c905b0bb6998d43ed133e72e2445f08125f86dfc96887e288701a`,
equal to the exact pinned-source
[`GetAccountResponse.json`](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/schema/json/v2/GetAccountResponse.json#L1-L112).
This corroborates the critical response shape against the retained binary; the
artifact stores schema hashes, not secret values or invented response bodies.

The official OpenAI documentation describes
[managed ChatGPT authentication](https://learn.chatgpt.com/docs/app-server), in
which Codex persists and refreshes its tokens, and documents
[`file`, `keyring`, `auto`, and `ephemeral` storage](https://learn.chatgpt.com/docs/auth).
Those current pages orient the investigation only. They do not pin this release
or add a method absent from its source and generated schema.

No installed CLI was started. No real home, `auth.json`, keyring, credential,
account value, login flow, provider endpoint, or model request was inspected or
used. Inspection was limited to public exact-commit source and the retained
credential-free schema artifact.

## Registered surface versus dormant records

The protocol macro defines `ClientRequest` as the requests a client can send,
including each wire name and response type
([`common.rs` lines 208-294](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/common.rs#L208-L294)).
Its registered v2 account methods and response types are enumerated at
[`common.rs` lines 1201-1262](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/common.rs#L1201-L1262)
and `account/read` at
[`common.rs` lines 1368-1372](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/common.rs#L1368-L1372).
The server dispatcher mirrors those account variants, plus deprecated
`getAuthStatus`, at
[`message_processor.rs` lines 1570-1613](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/message_processor.rs#L1570-L1613).

The retained binary's generated inventory contains exactly these account-prefixed
methods: `account/bedrock/discover`, `account/bedrock/setup`,
`account/login/cancel`, `account/login/start`, `account/logout`,
`account/rateLimitResetCredit/consume`, `account/rateLimits/read`,
`account/read`, `account/sendAddCreditsNudgeEmail`, `account/usage/read`, and
`account/workspaceMessages/read`. It contains no `account/sessions/*` method.

- `account/read` returns ChatGPT `email` and `planType`, not an account,
  workspace, tenant, organization, or stable principal id
  ([`account.rs` lines 22-58](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/account.rs#L22-L58),
  [`account.rs` lines 524-540](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/account.rs#L524-L540)).
  Email is expressly ineligible as ADR 0020's principal.
- `account/rateLimits/read` can return one optional backend `accountId`, but no
  principal or complete current authority tuple
  ([`account.rs` lines 314-325](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/account.rs#L314-L325)).
  Its handler observes a backend `user_id` only while filtering upsell content,
  then returns `account_id` and discards `user_id`
  ([`account_processor.rs` lines 1192-1213](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/request_processors/account_processor.rs#L1192-L1213)).
- `account/usage/read` and `account/workspaceMessages/read` return usage and
  message data, not identity authority
  ([`account.rs` lines 425-445](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/account.rs#L425-L445)).
  Login responses and account notifications expose flow ids, auth mode, or plan
  type, not the missing tuple
  ([`account.rs` lines 132-166](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/account.rs#L132-L166),
  [`account.rs` lines 534-548](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/account.rs#L534-L548)).
- Deprecated `getAuthStatus` returns only auth method, an optional bearer token,
  and whether OpenAI auth is required
  ([`v1.rs` lines 186-206](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v1.rs#L186-L206)).
  Extracting identity from that token would be the forbidden token-export/parser
  design, not a supported non-secret metadata path.

By contrast, the same source declares `AccountSession` with `user_id`,
`selected_workspace_account_id`, and `workspaces`, whose entries carry
`account_id`
([`account.rs` lines 191-260](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/account.rs#L191-L260)).
No such request appears in the generated binary method inventory, the source
`ClientRequest` registrations, or the dispatcher. A declared response-shaped
type is not a supported callable interface.

## Narrow store trace and limit

Pinned source defines `File` mode as persistent
`CODEX_HOME/auth.json`, alongside `Keyring`, `Auto`, and non-persistent
`Ephemeral`
([`types.rs` lines 106-119](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/config/src/types.rs#L106-L119)).
`cli_auth_credentials_store` selects that backend
([`config_toml.rs` lines 251-264](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/config/src/config_toml.rs#L251-L264)).

The file backend resolves exactly `codex_home.join("auth.json")` and saves by
opening that path with truncate/write/create, mode `0600` on Unix
([`storage.rs` lines 154-226](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/storage.rs#L154-L226)).
Managed auth loads the configured persistent backend, and token refresh saves
through the same storage object
([`manager.rs` lines 1517-1528](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L1517-L1528),
[`manager.rs` lines 1555-1578](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/login/src/auth/manager.rs#L1555-L1578)).
`CODEX_HOME` itself is selectable and canonicalized as a directory
([`config/mod.rs` lines 4747-4756](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/config/mod.rs#L4747-L4756)).

Therefore the smallest source-backed store candidate is a pre-existing,
vendor-created store provisioned by the operator, with `auth.json` bind-mounted
read/write at that one path inside an otherwise fresh disposable `CODEX_HOME`,
with trusted configuration forcing `file`. `auto` is unsuitable because it may
select keyring or file; `keyring` requires broader OS credential-store access;
`ephemeral` cannot preserve managed login. Constructicon would mount but never
read, copy, hash, parse, or journal the file.

This investigation did not prove mount aliasing, refresh-in-place behavior under
the Linux boundary, store locking, quiescence, logout/repair, or exclusion from
workers. Those remain N3/N4 physical and authenticated conformance work only if
a future supported identity interface first makes the candidate viable.

## Disposition and smallest future option

The exact missing proof is a **registered, dispatched, pinned vendor operation**
that returns a non-secret stable principal plus the current value of every
independently selectable workspace, tenant and organization scope needed to
distinguish authority switches, and whose qualified refresh path preserves
that tuple. No supported, registered app-server operation in `0.153.4`
supplies it.

Do not patch the vendor, parse its auth cache or bearer token, use email, infer
identity from a model stream, weaken the tuple, or start N1 around an assumed
future RPC. The smallest future option is a separately authorized source/schema
assessment of a vendor release or supported interface that actually registers
and dispatches the complete metadata response. Selecting a changed binary then
requires the rev-2 plan's full catalog, startup, placement, mediation, and
lifecycle requalification before implementation. Until such a decision, native
account mode remains unavailable; the gateway route remains a separate owner
choice under ADR 0018.

Reproducible public-source checks, requiring no Codex login or native binary
execution (the GitHub CLI uses its existing GitHub authentication):

```powershell
gh api repos/openai/codex/git/ref/tags/rust-v0.153.4
gh api repos/openai/codex/git/tags/042fb41b7c813ac7999105e886b2b7aa715b5081
gh api -H "Accept: application/vnd.github.raw+json" "repos/openai/codex/contents/codex-rs/app-server-protocol/src/protocol/common.rs?ref=3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
gh api -H "Accept: application/vnd.github.raw+json" "repos/openai/codex/contents/codex-rs/app-server-protocol/src/protocol/v2/account.rs?ref=3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
gh api -H "Accept: application/vnd.github.raw+json" "repos/openai/codex/contents/codex-rs/login/src/auth/storage.rs?ref=3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"
```
