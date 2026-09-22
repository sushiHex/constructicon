# M8 Claude Code interface screen

Status: credential-free source and documentation screen, 2026-09-22
(America/Los_Angeles). **Every load-bearing citation was re-verified the same
day by a second reader**, who corrected several claims; the corrections are
listed under [Second reading](#second-reading-what-changed). This is not
implementation authority, login approval, candidate selection, or production
qualification. It is the N6 analogue of the
[Codex subscription-mode screen](M8-subscription-mode-interface-screen.md).

Repository context: accepted [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md)
and [rev 3](../milestones/M8-live-executors-rev3.md) on `main` at
`6bc9500616f0f2815dd9a79d060e2ba983f6eae5`, after N2 merged. Rev 3 N6
(`M8-live-executors-rev3.md:160-170`) and issue
[#40](https://github.com/sushiHex/constructicon/issues/40) scope this work:
Claude qualifies "with its own pinned protocol, supported direct login, mode
observation, layout, startup, tool mediation and egress evidence", and its
credential-free interface review "may run alongside Codex work".

## Result

**The pinned Claude Code `2.1.267` has a callable, non-secret subscription-mode
observation that needs no model request: the `account` object returned by a
repeated stream-json `initialize` control request, which the CLI recomputes on
every call. It can carry ADR 0021's per-turn gate the way `account/read`
carries it for Codex. The candidate does not qualify as a whole.** Of the ten
ADR 0021 requirements screened:

- four are SATISFIED at the source and documentation level: supported direct
  login, exclusion of alternate credentials, the mode observation, and refresh
  detection;
- one is NOT SATISFIED for Team and Enterprise subscriptions: cloud-managed
  inputs;
- the remainder are UNKNOWN, each with named resolving evidence.

Nothing here was executed.

The decisive finding is **server-managed settings**. For a Team or Enterprise
login, Anthropic's servers deliver settings at startup and hourly during the
session. Those settings can carry hooks and environment variables. They outrank
every local source including command-line arguments. In `-p` or Agent SDK runs
they are applied without the approval dialog. The vendor states that you
"can't disable them from the SDK" and that "filesystem isolation does not
remove them". That is exactly the vendor-side widening ADR 0021 forbids
(`0021:267-275`).

At this pin the fetch is gated on the client side: a Pro or Max OAuth login
with no API key is ineligible and makes no fetch. So **the smallest Claude
profile that can qualify is individual Pro/Max only**, with every other plan
refused by the same per-turn reading. That narrows ADR 0021's outcome, which
names Claude subscriptions without a plan. It needs no amendment, because the
ADR already requires every reachable input to be excluded, fixed or
constrained, and says a profile that cannot do so cannot qualify
(`0021:267-275`). The owner should know it before N6 proceeds.

The observation **collapses one distinction that does not matter**. It reports
a plan as a display string (`"Claude Pro"`, `"Claude Max"`, …) and falls back
to `"Claude API"` when the plan is unknown, so the gate must accept exact
strings rather than "has a subscription". A token read from an undocumented
well-known file, combined with an environment-declared plan, is
indistinguishable from a `/login` credential. Both are subscription
credentials, and both are excluded by construction. A token supplied through
the file-descriptor variable is **not** collapsed: it reports its own
`tokenSource` and no plan.

## Pins and evidence boundary

npm `@anthropic-ai/claude-code`, dist-tag **`stable` = `2.1.267`**, published
2026-09-09T18:25:42Z. The `latest` and `next` tags are `2.1.280`, published
2026-09-22T15:44:39Z. `stable` was pinned because it is the vendor's own stable
channel. Nothing here speaks for 2.1.280.

| Artifact | Registry integrity (reproduced locally) | Content digest |
| --- | --- | --- |
| `@anthropic-ai/claude-code@2.1.267` (wrapper) | `sha512-0rErYxMp/5uJKt2Z8zJVRmuGEijTiDOb659YnELpGsxyrOp0BKhoOrT8tyNrK5yn8VLYXxc3X3KXfT9woL0R4g==` | tgz SHA-256 `b7896127c6ae4382a4a688d90189ab574dbe495aff81153dea909576d299e439` |
| `@anthropic-ai/claude-code-linux-x64@2.1.267` | `sha512-/tbh7mVwKlsGV4NHSMp+Bxulu2Ly+DSnD7JcsSQex8UO2G7pq8sYXIXXNLR1l2U04Oia/qzH8UkUonRXkwWJeg==` | `package/claude` SHA-256 `0399c793ff571d5946ef923d80b4f330d05ac4b6842a6b0775468f5d389403c0` |
| `@anthropic-ai/claude-agent-sdk@0.3.267` | `sha512-LwpOY09+9nhN1AUvME9ap8hpGd2AP6GlKsrWIsHCJZw/4kbZoUaD2maxjmWLF4X/GgDBwQ7xW1D2n6Srj6vOBw==` | tgz SHA-256 `4177598847f37041aadcfe1a922a0153e2e58495100521233fc587e1c0839485` |

The wrapper bundles no CLI implementation. Its `bin/claude.exe` is a 500-byte
shell stub that prints an install error; its only scripts are the postinstall
`install.cjs` and a fallback launcher `cli-wrapper.cjs` that spawns the
platform binary. The binary arrives through eight platform
`optionalDependencies`. The SDK's `manifest.json` names version `2.1.267`,
commit `a9e1808c8204fef901336d54bac7d4ab442955cb`, and a `linux-x64` checksum
equal to the SHA-256 of the unpacked Linux binary above. That is two
independent registry paths agreeing on one pinned binary.

**Corpora.** Three were read:

1. The Linux binary, read as bytes: a Bun-compiled executable whose 1,642
   embedded JavaScript chunk headers all carry `// Version: 2.1.267`.
2. The SDK's `sdk.d.ts` (8898 lines) and `sdk.mjs`.
3. The current published documentation at `code.claude.com`, fetched as raw
   Markdown with `curl`, plus one help-centre page with its tags stripped.

Binary citations are written **B@offset**: the byte offset of, or inside, the
quoted match in the pinned `package/claude`. The bundle is minified, so
identifiers such as `GZ` or `pc` are chunk-local and meaningful only at that
offset. Where a name is imported from another chunk, it was resolved by
matching the import list against a chunk whose export list contains the same
names. Chunk file names were not mapped to offsets directly, so each such
resolution is an export-set match, not a proven link.

**Nothing was executed.** No Claude binary ran, not even `--version`: the
pinned artifact is the Linux build and this host is Windows, and running the
Windows build would not pin the Linux one. No login, account, credential file,
keychain, model call or vendor request was involved.

Commands run: `npm view`, `npm pack` and `tar` for the three tarballs;
`sha256sum` and `openssl dgst -sha512`; `curl` for the documentation; and
read-only Python byte searches over the binary. Vendor documentation describes
the current product, not this pin. Where the two disagree, the binary governs.

## The conjunction

| # | ADR 0021 requirement | Where | Verdict |
| --- | --- | --- | --- |
| R1 | Supported direct login; vendor owns creation, storage, refresh and logout | `0021:208-215`, `219-221` | **SATISFIED** (docs); login itself is N4 |
| R2 | Proven narrow store layout; refresh stays inside it | `0021:127-137`, `171-176`, `212-215` | **UNKNOWN**: single-file candidate is source-feasible; refresh locks sit outside the file |
| R3 | Alternate keys, helpers, provider overrides and paid fallback excluded by fixed environment and configuration | `0021:228-230` | **SATISFIED** by construction (allowlist), except R8's input |
| R4 | Supported, non-secret, fresh per-session mode observation before each turn and before acceptance; no model request | `0021:230-236`, `239-240` | **SATISFIED**, with a transport caveat |
| R5 | Refresh cannot silently select API/cloud authentication mid-turn | `0021:236-238` | **SATISFIED** as for Codex; fixture owed |
| R6 | Surface overage facts; `forbidden` needs proved mechanical refusal | `0021:242-254` | Surfacing **SATISFIED**; `forbidden` **UNKNOWN** |
| R7 | Bounded startup: no model request or account-dependent code before the gate; protocol enforces the phase | `0021:258-265` | **UNKNOWN**: one pre-turn model path found and guarded |
| R8 | Account and cloud-managed inputs excluded, fixed or constrained; vendor-side change cannot widen | `0021:267-275` | **NOT SATISFIED** (Team/Enterprise); **UNKNOWN** (Pro/Max) |
| R9 | Every model-selectable operation is an admitted callback or unreachable | `0021:103-116` | **UNKNOWN**: interface fits, one vendor-mandated exception |
| R10 | Fixed qualified vendor destinations; no arbitrary proxy/DNS/URL; startup and redirects proved | `0021:277-288` | **UNKNOWN** |

The "SATISFIED" verdicts are interface verdicts in the Codex screen's sense.
They mean the pinned artifact offers what the requirement needs. They do not
mean it was observed working.

## Findings

### R1: supported direct login exists and is permitted for this shape

`claude auth login` is documented, with `--console` "to sign in with Anthropic
Console for API usage billing instead of a Claude subscription"
([CLI reference](https://code.claude.com/docs/en/cli-reference)). The
credential-use guidance draws the line ADR 0021 relies on. It says Anthropic
does not permit developers "to route requests through Free, Pro, or Max plan
credentials on behalf of their users". It then says this does not "prevent an
end user from signing in to the unmodified Claude Code binary with their own
Claude subscription, including where a platform hosts Claude Code"
([legal and compliance](https://code.claude.com/docs/en/legal-and-compliance)).
ADR 0021's operator is that end user (`0021:66-69`).

The ADR-cited billing notice still reads "paused": "For now, nothing has
changed: Claude Agent SDK, claude -p , and third-party app usage still draw from
your subscription's usage limits"
([help centre](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan),
tag-stripped, so the space before the comma is the page's markup). Per rev 3
N6, that is billing guidance and not login permission. It is recorded, not
relied on. This is not legal advice.

### R2: the single-file layout is source-feasible, not proved

- **Location.** On Linux, credentials are "stored in
  `~/.claude/.credentials.json` with file mode `0600`", and under
  `CLAUDE_CONFIG_DIR` when that is set
  ([authentication](https://code.claude.com/docs/en/authentication)). The
  binary agrees: storage path `join(Gy(), ".credentials.json")` beside the
  literal "Warning: Storing credentials in plaintext." (B@180872875,
  literal at B@180872952). `Gy()` honours an undocumented
  `CLAUDE_SECURESTORAGE_CONFIG_DIR` before falling back to the config
  directory (B@180868649). A session-store resume helper spells out the whole
  layout (B@200137849):
  - `CLAUDE_CONFIG_DIR ?? ~/.claude` holds `.credentials.json` and
    `settings.json`;
  - `.claude.json` sits at `CLAUDE_CONFIG_DIR ?? $HOME`.
- **Refresh write path.** Refresh saves only the `claudeAiOauth` record through
  the storage `mutate` (B@181853512). Both credential-store writers, the
  plaintext store's `In` (B@180871687 imports it; B@179819463 defines it) and
  the newer store's `writeCredentials` (B@189975166), call one helper, `mce`.
  It stages `<target>.tmp.<8 hex>` beside the target, then renames it over the
  target (B@179819526). If the rename fails with an errno in
  `QT = {EXDEV, EPERM, EEXIST, EBUSY}` (B@179815953), it falls back to an
  in-place truncate-and-write and unlinks the staged file. A rename onto a
  single bind-mounted file fails with `EBUSY` on Linux, so a
  `.credentials.json` bind-mounted read/write into a disposable config
  directory is **source-feasible**, as `auth.json` was for Codex. The newer
  store module opens with `O_NOFOLLOW` and reports `refused-symlink`
  (B@189975686), so a symlinked store is refused rather than followed.
- **Change detection.** The in-process token cache is memoized
  (`Jt()`, B@181856921) and cleared when the credential file's mtime changes
  (B@181858786), or when the newer store's `dev:ino:size:mtimeNs` version
  changes (B@189979494). Both survive an in-place write to a bind mount.
- **Locks live outside the file.** OAuth refresh takes a lock at
  `Gy()/.oauth_refresh.lock` (B@181864768) and a legacy lock at
  `${realpath(Gy())}.lock`, a sibling of the configuration directory in its
  parent (B@181865173; `f_e` is `realpath`, resolved from the chunk's
  `fs/promises` import). A legacy-lock failure other than `ELOCKED` is logged
  and refresh continues on the new lock alone (B@181865245). Every storage
  `mutate` also takes `Gy()/.storage-write` through the same lock library
  (B@180872099), whose default lock path appends `.lock` (B@180862798).

What this does not establish, all N3/N4 work:

- whether a session runs with a fresh, empty `.claude.json`. That file holds
  `oauthAccount` and any legacy `primaryApiKey`, and the SDK docs say
  `~/.claude.json` is read regardless of `settingSources`
  ([Claude Code features](https://code.claude.com/docs/en/agent-sdk/claude-code-features));
- where the refresh and storage locks are placed and owned: two sit inside the
  configuration directory and one in its parent, so the disposable layout must
  provide both, and ADR 0021's store/lock recipe (`0021:127-137`) must name
  them;
- that the staged temporary file **transiently writes credential bytes into the
  disposable directory**, which disposal must therefore treat as
  credential-bearing;
- refresh behaviour under the real Linux boundary.

### R3: every identified alternate input is excludable by construction

The documented precedence runs cloud-provider variables, `ANTHROPIC_AUTH_TOKEN`,
`ANTHROPIC_API_KEY`, `apiKeyHelper`, `CLAUDE_CODE_OAUTH_TOKEN`, Anthropic
profiles and federation, and last "Subscription OAuth credentials from
`/login`" ([authentication](https://code.claude.com/docs/en/authentication)).
The binary adds sources the page does not list:

- `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`;
- a **well-known file** `/home/claude/.claude/remote/.oauth_token`
  (B@180824676), read whenever that descriptor variable is unset, with no
  remote-host guard on the read (B@180826403 synchronous, B@180827922
  asynchronous). Only the *write* that persists a token there is guarded by
  `CLAUDE_CODE_REMOTE` (B@180824900);
- `CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR` (B@181831258), and its own
  well-known file `/home/claude/.claude/remote/.api_key`, read the same way
  when that variable is unset (B@180832281). A key from either is reported as
  `apiKeySource: "ANTHROPIC_API_KEY"` (B@181835768);
- a Console `primaryApiKey` in `.claude.json`, reported as
  `"/login managed key"` (B@181877019);
- profiles under `~/.config/anthropic`. A profile named in `ANTHROPIC_PROFILE`,
  the federation variables, or an active `oidc_federation` profile outrank
  `/login`; an active `user_oauth` profile ranks below a working `/login`
  ([authentication](https://code.claude.com/docs/en/authentication)).

None of these needs a denylist. The v3 grant policy already fixes the
environment by **allowlist** (`0021:299-303`). The native zone's `HOME`, config
directory and `/home` are disposable constructions, and an empty
`settingSources` skips user, project and local settings
([TypeScript reference](https://code.claude.com/docs/en/agent-sdk/typescript)).
An input the adapter never supplies cannot select a credential. Unknown
variables fall to the allowlist, not to enumeration. The one input no local
construction removes is server-managed settings (R8). R4's reading is the
backstop for anything missed, because it reports every API-key source it finds.

### R4: the observation is a repeated `initialize`, not the SDK's cached accessor

**The carrier.** In print mode with `--input-format stream-json`, the CLI
handles an `initialize` control request (B@201114227). On a repeat, handler
`gh` takes a separate branch that answers `await tp(...)` (B@201186248). The
builder `tp` computes `account` by calling `GZ()` afresh (B@201189544), from
four inputs (B@181876435):

- the auth-token source `pc()` (B@181832113);
- the subscriber test `gt()` (B@181871434);
- the API-key source `Qp()` (B@181832886);
- the provider `Ie()`, taken from environment variables (B@180758422).

The response type is published: `SDKControlInitializeResponse.account:
AccountInfo` (`sdk.d.ts:4052-4062`), with optional `email`, `organization`,
`subscriptionType`, `tokenSource`, `apiKeySource` and an `apiProvider` enum
(`sdk.d.ts:23-33`).

**Supported, with a caveat.** The SDK's public `reinitialize()` is that
repeated request. The docs say it "Re-sends the `initialize` control request to
the running CLI and returns a fresh result instead of the cached first-connect
result … Requires Claude Code v2.1.195 or later"
([TypeScript reference](https://code.claude.com/docs/en/agent-sdk/typescript);
`sdk.d.ts:2717-2741`). Its documented purpose is transport-gap recovery, not
account polling. The repeat also (B@201186248):

- redelivers pending permission and dialog requests;
- re-registers hooks when it carries any, resolving any hook callback still
  pending (`sdk.d.ts:2727-2734`).

So the adapter must send it only between turns and without hooks. The CLI's
stream-json control protocol is published through the SDK's types and partly in
its docs, which address a client that "drives the CLI's control protocol
directly" in at least one place (the `interrupt` request's `cancel_queued`
field). It is not a standalone stable CLI specification. That caveat is
comparable to Codex's "experimental" app-server.

**Fresh, not cached init metadata.** The SDK's `accountInfo()` **is** cached,
`async accountInfo(){return(await this.initialization).account}` in
`sdk.mjs`, which reproduces issue #38's 2026-09-12 finding. Driving the wire
directly, as the Codex adapter does, avoids that cache: each `initialize`
recomputes. What it recomputes from is the process's credential cache, so a
second reading after a turn with no refresh is expected to be identical. That
is the same limit `codex_protocol.py:11-18` records for `account/read`.

**No secret, no model request.** `GZ()` emits no token field. Its email and
organization are account facts to read and discard, as with Codex. `tp`
contains no model call. Whether it performs other I/O, for example while
loading output styles, is UNVERIFIED (see R7).

**Rejected carriers:**

| Carrier | Why it is not the gate |
| --- | --- |
| SDK `accountInfo()` | Cached at initialization, as shown above |
| `system/init` `apiKeySource` | Emitted "at the start of each turn" (`sdk.d.ts:5172`), so it arrives after the turn has started. Usable as corroboration only |
| `claude auth status` | Another process, not "the executing session". Maps a Console `"/login managed key"` to `authMethod: "claude.ai"` (B@202466000); its JSON carries `email`, `orgId`, `orgName` and `subscriptionType` for that method (B@202467017) |

That last row updates the evidence gap the #38 screen left open: at this pin
the JSON fields are known.

**The refusal rule this implies.** Derived from `GZ()` and the plan-name
mapping (B@181874009: `"Claude Enterprise"`, `"Claude Team"`, `"Claude Max"`,
`"Claude Pro"`, default `"Claude API"`), accept only when all of these hold:

- `apiProvider == "firstParty"`;
- `subscriptionType ∈ {"Claude Pro", "Claude Max"}`;
- `tokenSource` is absent;
- `apiKeySource` is absent.

Everything else refuses:

- a missing `account` or a control error;
- `"Claude API"`, meaning a claude.ai-scoped token with an unknown plan;
- `"Claude Team"` or `"Claude Enterprise"`, per R8;
- any `tokenSource`, such as `CLAUDE_CODE_OAUTH_TOKEN`,
  `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`, `apiKeyHelper`, or `claude.ai`
  for a claude.ai token that is not a subscriber's;
- any `apiKeySource`, such as `ANTHROPIC_API_KEY`, `apiKeyHelper` or
  `/login managed key`;
- any provider other than first-party.

`GZ()` returns nothing unless the provider is first-party. It sets
`tokenSource` for `CLAUDE_CODE_OAUTH_TOKEN` and its file-descriptor variant
first; otherwise it sets `subscriptionType` when `gt()` holds; otherwise it
sets `tokenSource` for every source but a profile (B@181876435). `gt()`
requires `yl()` and inference scopes (B@181871434). `yl()` is false in bare
mode, under a profile, for a non-first-party provider, and whenever
`ANTHROPIC_AUTH_TOKEN`, an `ANTHROPIC_API_KEY`-sourced key, `apiKeyHelper` or
`CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR` is present (B@181831258). A Console
`/login managed key` does **not** make `yl()` false: such a session reports a
plan **and** an `apiKeySource`, which the rule's last clause refuses. `yl()`'s
two exceptions apply only when `kr()` holds, which is `CLAUDE_CODE_REMOTE` or a
`CLAUDE_CODE_ENTRYPOINT` of `claude-desktop`, `claude-desktop-3p` or
`local-agent` (B@181824599, B@181828680, B@179451277). The allowlist must
therefore exclude `CLAUDE_CODE_REMOTE` and must not set those entrypoints. The
plan strings are display text, pinned to this version, and a changed binary
requalifies anyway.

**The collapse.** A token from the well-known file gets inference scopes and
takes its plan from `CLAUDE_CODE_SUBSCRIPTION_TYPE` (B@181855895, `K_e`).
`pc()` names its source `CCR_OAUTH_TOKEN_FILE` (B@181832113), but `GZ()`
reports `subscriptionType` in place of that `tokenSource` whenever `gt()`
holds, so given that variable it reports exactly the shape `/login` does. The
file-descriptor variant does not collapse: `GZ()` reports its `tokenSource`
before testing `gt()`, and `Y1()` keeps the variable identifiable after the
descriptor is consumed (B@180831408, B@178995830). Both are subscription credentials, so the
collapse does not change the billing route. Both are excluded because the path
is absent and the variables are not allowlisted.

### R5: an honest mid-turn switch to API authentication is caught

Refresh writes only `claudeAiOauth` (B@181853512). API-key sources come from
the process environment (fixed), settings (sources emptied), `.claude.json`
(disposable), the well-known `/home/claude/.claude/remote/` files (absent) or
server-managed settings (refused plans, R8). A switch that the session
honestly reports adds `apiKeySource` or drops `subscriptionType`, and the
pre-acceptance `initialize` then refuses the result.

As with Codex, this defends against honest reports only. A client that
misreports its own mode is out of reach (`codex_protocol.py:20-24`). **The N3
analogue owes the fixture**: introduce an API credential mid-turn and prove the
result is refused.

### R6: overage facts are surfaced; `forbidden` has no client-side refusal

`rate_limit_event` carries `overageStatus`, `overageDisabledReason`,
`isUsingOverage` and a `credits_required` error code (`sdk.d.ts:4950-4981`).
The experimental `get_usage` control request (`sdk.d.ts:3751`) returns
`extra_usage.is_enabled` (`sdk.d.ts:3847`) without a turn. Surfacing
therefore holds.

Refusal at the included limit is vendor-side. The account's usage-credits
setting ("you can turn usage credits on or off", on claude.ai;
[costs](https://code.claude.com/docs/en/costs)) either lets requests continue
or yields the `credits_required` rejection, which comes from "a claude.ai
subscription whose included usage is exhausted"
([TypeScript reference](https://code.claude.com/docs/en/agent-sdk/typescript)).
The client offers no switch.

`subscription_overage="forbidden"` stays UNKNOWN. What would resolve it is N4
evidence that `extra_usage.is_enabled == false`, read before the turn and again
before acceptance, coincides with vendor refusal at the limit. ADR 0021 already
says an unproved arrangement makes that profile unavailable (`0021:247-248`).
The companion [spend-bound research](../../../research/m8-subscription-spend-bounds.md)
records the vendor's own words on disabling credits.

### R7: one pre-turn model request exists at this pin, and print mode skips it

The binary contains one `quota_check` request, `messages.create` with
`max_tokens:1` and content `"quota"` (B@186311556). The startup prefetch calls
it for subscribers (B@193136064, through `ebt`). Both callers, that prefetch
and a rate-limit re-check through `VXn`, go through `probeQuotaStatus`, which
returns early when `Re()` is true (B@186322351). Both chunks import `Re` from
the same module name, resolved by export-set match to
`function Re(){return!n().host.launchOptions.isInteractive()}`
(B@178990151). **Non-interactive sessions therefore skip it.**

Otherwise the stream-json design starts a turn only on a user message. So:

1. launch;
2. `initialize`, which also carries the SDK MCP handshake, answered as metadata
   while `tools/call` stays refused;
3. mode reading and catalog reading;
4. only then the first user message.

That sequence is the natural phase boundary.

No other pre-turn model path was found. **That is absence of evidence from a
minified bundle, not a proof.** Startup also makes non-model requests that
share `api.anthropic.com` with inference: the documentation lists feature flag
fetches and telemetry event logging there
([network config](https://code.claude.com/docs/en/network-config)), and
server-managed settings "require a direct connection to `api.anthropic.com`"
([server-managed settings](https://code.claude.com/docs/en/server-managed-settings)).
ADR 0021 already says a firewall alone cannot separate those (`0021:263-265`).

**Resolving evidence, credential-free:** an account-empty launch with native
egress denied should complete `initialize`, the `account` reading and the
catalog reading with zero connection attempts. The gate phase would then need
no network at all, which is stronger than separating destinations. N4 repeats
it with a real store.

### R8: server-managed settings fail the clause for Team and Enterprise

What the vendor documents
([server-managed settings](https://code.claude.com/docs/en/server-managed-settings)):

- **Timing.** "Claude Code fetches settings from Anthropic's servers at
  startup and polls for updates hourly during active sessions."
- **Content.** Every `settings.json` key is supported except those restricted
  to OS-level policy delivery; "This includes hooks, environment variables"
  and managed-only settings.
- **Precedence.** Server-managed and endpoint-managed settings "occupy the
  highest tier … No other settings level can override them, including command
  line arguments", and within that tier server-managed settings are checked
  first.
- **Non-interactive runs.** "A non-interactive run, such as `claude -p` or an
  Agent SDK session: Claude Code can't show the dialog, so when the delivered
  settings would require approval, it applies them for that run only."
- **No local opt-out.** The SDK page: "you can't disable them from the SDK",
  and "filesystem isolation does not remove them"
  ([Claude Code features](https://code.claude.com/docs/en/agent-sdk/claude-code-features)).

A Team or Enterprise administrator, or a vendor-side change, can therefore add
a hook, an `apiKeyHelper` or a base-URL variable to a running native session.
The hook would execute in the zone that holds the store and the egress. That is
the widening `0021:270-275` forbids, and the ADR's own disposition applies:
"this profile cannot qualify".

**Pro/Max is ineligible at this pin**, documented and in source. The
documentation limits delivery to "A Team or Enterprise OAuth login", an OAuth
token from `CLAUDE_CODE_OAUTH_TOKEN`, a directly configured API key, or a
`user_oauth` profile. The binary's eligibility check (B@181929706) refuses a
hermetic remote session, a third-party provider, a custom base URL and a
sandboxed entrypoint; admits a pinned gateway; returns eligible for plan
`team`, `enterprise` or **unknown**; and returns eligible for a found profile or
API key. Otherwise it returns `unsupported_subscription`, and a Pro/Max login
with no API key falls through to that, so no fetch happens. R4's rule already
refuses every eligible shape.

The check's first branch, `if(qb())return{eligible:!0}`, is dead at this pin:
`qb` is `function qb(){return}` (B@179729699), in the chunk whose export list
matches the eligibility chunk's import of `{sNn,lNn,Gle,qb,cNn}`. That
resolution is an export-set match, as described under the evidence boundary.

One residue keeps Pro/Max at UNKNOWN rather than SATISFIED: the plan is an
account fact the vendor controls. A mid-session plan change is observed at the
next reading, but ADR 0021 warns that "Post-turn comparison alone cannot undo
an earlier authority widening" (`0021:273-274`). N4 must show that no settings
fetch occurs for the provisioned Pro/Max binding.

The other account-scoped inputs are excludable:

| Input | Exclusion |
| --- | --- |
| claude.ai MCP connectors (account-delivered tools) | `strictMcpConfig`, `disableClaudeAiConnectors`, or `ENABLE_CLAUDEAI_MCP_SERVERS=false` ([Claude Code features](https://code.claude.com/docs/en/agent-sdk/claude-code-features)) |
| Feature-flag fetching | `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, which "Also disables feature-flag fetching" ([environment variables](https://code.claude.com/docs/en/env-vars)) |
| Auto memory | `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` |
| Endpoint-managed policy | Absent, because the native zone's `/etc` is ours |

`policy-limits.json`, a separate server-fetched file (fetcher at B@182053234;
named in a configuration-directory file list at B@189746195), was not
screened.

### R9: the catalog maps onto one in-process MCP server, with one exception

The Codex analogue of dynamic tools is an **SDK-type MCP server**: `type:
"sdk"` in `--mcp-config`, named in `initialize.sdkMcpServers`. Its JSON-RPC
traffic, including `tools/call`, reaches the host as `mcp_message` control
requests over the same stdio (`sdk.d.ts:4173-4183`; `McpSdkServerConfig`,
`sdk.d.ts:1090`). The model's calls reach the adapter with no extra process in
the native zone.

The documented flags:

| Flag or variable | Documented effect |
| --- | --- |
| `--tools ""` | Disables all built-in tools |
| `--strict-mcp-config` | "Only use MCP servers from `--mcp-config`, ignoring all other MCP configurations" |
| `--setting-sources=` | An empty source list skips user, project and local settings, which removes their hooks, skills and plugins |
| `--disable-slash-commands` | Disables all skills and commands |
| `--no-session-persistence` | Sessions are not saved to disk and cannot be resumed |

Sources: [CLI reference](https://code.claude.com/docs/en/cli-reference) and
[TypeScript reference](https://code.claude.com/docs/en/agent-sdk/typescript).
The official SDK's launch builder emits `--tools ""`, `--mcp-config`,
`--setting-sources=`, `--strict-mcp-config` and `--no-session-persistence`
from its options (`sdk.mjs`); it has no `--disable-slash-commands`, which the
binary defines as its own option with the help text "Disable all skills"
(B@193338165). The adapter's control channel is trusted
and host-only; host requests such as `mcp_set_servers`, `read_file` and
`mcp_call` are never model-selectable and must never carry untrusted input.

**The exception.** `EndConversation` cannot be removed while any other tool
remains. The docs say deny and ask rules, `--disallowedTools` and `--tools` all
fail, and PreToolUse hooks do not run for it; it "does nothing except end the
conversation, never reading or modifying files or data"
([tools reference](https://code.claude.com/docs/en/tools-reference)). It is not
mechanically unreachable. The fixed catalog must name it as a vendor-owned
terminal operation, and the adapter must map it to a non-success outcome.

**Pre-turn catalog observation.** `get_context_usage` with
`detail:'summary'`, which avoids token-count API calls (`sdk.d.ts:3631-3635`),
lists `mcpTools`, `systemTools` and `deferredBuiltinTools`. `mcp_status` lists
servers with their `scope`, including `claudeai` (`sdk.d.ts:1117-1156`). The
effective inventory under these flags is UNKNOWN until observed.

**Resolving evidence, credential-free:** an account-empty launch with the fixed
flags, reading both, must list exactly the adapter's callbacks plus
`EndConversation`. ADR 0021 says a claimed empty inventory proves nothing
(`0021:108`), so this must be observed, not inferred.

### R10: destinations are few and documented; nothing is proved

The documented hosts that matter here
([network config](https://code.claude.com/docs/en/network-config)):

| Host | Carries |
| --- | --- |
| `api.anthropic.com` | "Claude API requests, including the WebFetch domain safety check, feature flag fetches, and telemetry event logging" |
| `platform.claude.com` | "OAuth token exchange, refresh, and revocation also go to this host for claude.ai accounts" |
| `claude.ai` | "claude.ai account authentication"; whether a running session contacts it is UNKNOWN |
| `mcp-proxy.anthropic.com`, the Datadog intakes | Removable by the R8 connector settings and by `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` |

The page lists further hosts for sign-in in a browser, installers and updates,
plugins, documentation lookups, artifacts and changelogs. Whether any of them is
reachable under the fixed flags and environment is UNKNOWN until observed.

`ANTHROPIC_BASE_URL` redirection is closed by the environment allowlist and the
emptied settings sources for Pro/Max. The claim that the running set is exactly
`{api.anthropic.com, platform.claude.com}` is UNKNOWN. So are redirects and
resolver behaviour. They belong to N3 fixtures and N4/N5 observation.

## What cannot be learned without a login

These become N6 work under separate authorization (N4 and N5 lanes):

- the `account` object's actual values for the provisioned binding, and that
  they match the refusal rule's accept shape;
- whether a claude.ai `/login` store yields exactly `"Claude Pro"` or
  `"Claude Max"` with no `tokenSource`;
- real refresh behaviour through a bind-mounted `.credentials.json`: in-place
  fallback, lock placement, the temporary-file residue, and a fresh
  `.claude.json`;
- that no server-managed settings fetch occurs for the Pro/Max binding;
- actual startup and model-session destinations, redirects and TLS;
- the vendor's refusal at the included limit with usage credits off.

Everything else in R7 and R9 has a credential-free resolving test and belongs to
the N2 analogue.

## Disposition

**No ADR amendment is proposed.** N6 may proceed to its credential-free N2
analogue, naming repeated `initialize` as the mode interface. The owner should
see one scoping consequence first: **only individual Pro and Max plans can
qualify at this pin**. Team and Enterprise are refused by the gate, because
their cloud-managed settings cannot be excluded.

Obligations this screen adds:

- **N2 analogue (credential-free):**
  - speak stream-json directly, as the Codex adapter speaks the app-server,
    with no SDK dependency;
  - send `initialize` before the first user message and again before
    accepting the result, each time without hooks;
  - implement the refusal rule above, treating every non-matching,
    missing or erroring reading as refusal;
  - fix the environment by allowlist, including
    `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`,
    `ENABLE_CLAUDEAI_MCP_SERVERS=false` and
    `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, and excluding `CLAUDE_CODE_REMOTE`
    and the desktop and local-agent `CLAUDE_CODE_ENTRYPOINT` values;
  - launch with `-p --input-format stream-json --output-format stream-json
    --verbose --tools "" --strict-mcp-config --mcp-config <one sdk server>
    --setting-sources= --disable-slash-commands --no-session-persistence`;
  - admit `EndConversation` as a terminal non-success;
  - prove the offline-gate and catalog tests from R7 and R9 against an
    account-empty store.
- **N3 analogue:**
  - owe the mid-turn API-switch fixture;
  - prove the bind-mounted single-file layout, including the temporary
    staging file's disposal and the placement of `.oauth_refresh.lock`,
    `.storage-write.lock` and the parent-directory legacy lock;
  - keep `/home/claude/.claude/remote/`, `~/.config/anthropic` and any
    managed-settings path out of the native zone.
- **N4 analogue (authorized):** record the established `account` shape in the
  store-conformance revision, and prove that no settings fetch occurs and which
  destinations are contacted.

## Considered and rejected as unnecessary

| Option | Why rejected |
| --- | --- |
| The TypeScript Agent SDK as runtime | Adds Node and a cached `accountInfo()`; the wire suffices |
| `--await-initialize` | Hidden (`.hideHelp()`, B@193325940); governs plugins only |
| `CLAUDE_SECURESTORAGE_CONFIG_DIR` | Undocumented, so not a supported layout |
| `claude auth status` as the gate | Not the executing session |
| `canUseTool` / `--permission-prompt-tool` as mediation | Not a universal interceptor, per the 2026-09 feasibility record; the catalog, not permissions, is the boundary |
| `forceLoginMethod` / `forceLoginOrgUUID` managed settings | Restrict login paths, or pin an organization; neither is needed for billing route |
| `--bare` | Does not read OAuth, so subscription login is unusable (`CLAUDE_CODE_SIMPLE`, documented as equivalent to `--bare`: "OAuth tokens and keychain credentials are not read"; [environment variables](https://code.claude.com/docs/en/env-vars)) |
| `claude setup-token` / `CLAUDE_CODE_OAUTH_TOKEN` | An externally supplied token, which ADR 0021 excludes |
| Running the binary for `--version` or `--help` | The pin is established by two registry digests without it |
| Pinning 2.1.280 | `latest`, not `stable`; surveying it would start an upgrade loop |

## Limits

- **Absence claims are bounded.** "No other pre-turn model path", "no network in
  `tp`" and the input enumerations come from targeted searches of a minified
  bundle. They are not exhaustive. The second reading found one input the
  first missed (the well-known `.api_key` file), which is evidence that the
  enumeration is incomplete rather than that it is now complete.
- **Cross-chunk names are export-set matches.** `Re`, `GZ` and `qb` were each
  resolved to a chunk whose export list contains the imported names; no chunk
  file name was mapped to an offset.
- **Some claims rest on documentation alone.** Documentation describes the
  current product, not 2.1.267, and several quoted sentences carry version
  qualifiers newer than this pin. For example, "Requires Claude Code
  v2.1.268" appears for unrelated keys in the TypeScript and settings
  references.
- **Scope of this screen.** No vendor clarification was sought. No
  `policy-limits.json`, telemetry content, or subagent or plugin internals were
  screened.
- **Legal text.** The legal and billing pages are recorded as the ADR treats
  them: orientation, not qualification or legal advice.

## Second reading: what changed

The second reader re-fetched the registry metadata, re-downloaded all three
tarballs, reproduced every integrity and digest above, re-read every B@offset
against the pinned binary, re-checked every `sdk.d.ts` line and re-fetched
every quoted documentation passage with `curl`. The verdicts stand. The
corrections:

- **Unguarded read, wrong offset.** The draft cited B@180824900 for the
  well-known token file's missing remote-host guard; that offset is the
  *write*, which is guarded. The unguarded reads are at B@180826403 and
  B@180827922.
- **A missed input.** `/home/claude/.claude/remote/.api_key` is read when
  `CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR` is unset. The refusal rule already
  catches it.
- **The collapse was overstated.** The draft said the file-descriptor token
  also reports the `/login` shape. It does not; only the well-known file does.
- **`yl()` was overstated, and its exception understated.** A Console
  `/login managed key` leaves `yl()` true; the refusal rule, not `yl()`,
  refuses it. `kr()` also holds for three `CLAUDE_CODE_ENTRYPOINT` values, not
  only `CLAUDE_CODE_REMOTE`, which adds an allowlist obligation.
- **Two unknowns resolved.** The refresh locks were traced (the draft said
  they could not be), which adds a parent-directory lock to the layout; and
  `qb()` returns `undefined`, removing one of R8's two Pro/Max residues.
- **Documentation fidelity.** The network page lists feature flags and
  telemetry on `api.anthropic.com`, not "profile" or "settings"; settings
  delivery is sourced to its own page instead. `downloads.claude.ai` was
  removed from the "removable" row, since the documented non-essential-traffic
  switch names auto-updates but the host also serves plugin downloads. The
  `--bare` quote is from the `CLAUDE_CODE_SIMPLE` row. Profile precedence is
  stated per the page's table. The "drives the CLI's control protocol
  directly" sentence is scoped to one request and is now cited that way.
- **The SDK launch builder** does not emit `--disable-slash-commands`; the
  draft said it built exactly the listed arguments.
- **The wrapper** does ship two scripts, a postinstall and a fallback
  launcher; the draft said it shipped "no JavaScript CLI any more", a history
  claim this reading did not check. The `latest` publication time was added.
- **Line and offset precision.** `system/init` is `sdk.d.ts:5172`,
  `is_enabled` is `sdk.d.ts:3847`, `GZ` and `tp` start at B@181876435 and
  B@201189544, and two ADR ranges were narrowed to the sentences they cite
  (`0021:247-248`, `0021:273-274`).

## Reproducing this screen

Public, credential-free, and executing no Claude binary:

```bash
npm view @anthropic-ai/claude-code dist-tags time --json
npm view @anthropic-ai/claude-code@2.1.267 dist optionalDependencies bin --json
npm pack @anthropic-ai/claude-code@2.1.267 @anthropic-ai/claude-code-linux-x64@2.1.267 @anthropic-ai/claude-agent-sdk@0.3.267
openssl dgst -sha512 -binary <tgz> | base64 -w0          # compare with dist.integrity
sha256sum package/claude                                 # compare with SDK manifest.json linux-x64
curl -sL https://code.claude.com/docs/en/<page>.md       # authentication, cli-reference, env-vars,
                                                         # network-config, server-managed-settings,
                                                         # tools-reference, legal-and-compliance, costs,
                                                         # agent-sdk/typescript, agent-sdk/claude-code-features
```

Binary offsets were located with a read-only byte search: a regex over a
memory-mapped copy of the file, printing context. For example,
`subtype==="initialize"`, `function GZ\(\)`, `function pc\(\)\{`,
`QT=new Set\(`, `content:"quota"`, `\.oauth_refresh\.lock` and
`"--await-initialize"`. Cross-chunk names were resolved by reading the
`// Version: 2.1.267` chunk that contains an offset, its `import{…}from` list,
and its closing `export{…}` list. The offsets are stable only for the SHA-256
above.

## Sources

- Registry: `https://registry.npmjs.org/@anthropic-ai/claude-code`,
  `…/claude-code-linux-x64/-/claude-code-linux-x64-2.1.267.tgz`,
  `…/claude-agent-sdk/-/claude-agent-sdk-0.3.267.tgz`
- Documentation (raw Markdown): [authentication](https://code.claude.com/docs/en/authentication),
  [CLI reference](https://code.claude.com/docs/en/cli-reference),
  [environment variables](https://code.claude.com/docs/en/env-vars),
  [network config](https://code.claude.com/docs/en/network-config),
  [server-managed settings](https://code.claude.com/docs/en/server-managed-settings),
  [settings reference](https://code.claude.com/docs/en/settings-reference),
  [tools reference](https://code.claude.com/docs/en/tools-reference),
  [costs](https://code.claude.com/docs/en/costs),
  [legal and compliance](https://code.claude.com/docs/en/legal-and-compliance),
  [TypeScript reference](https://code.claude.com/docs/en/agent-sdk/typescript),
  [Claude Code features](https://code.claude.com/docs/en/agent-sdk/claude-code-features)
- Help centre: [Agent SDK with your Claude plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
- Repository: `docs/adr/0021-subscription-executors-bind-operator-stores.md`,
  `docs/plans/milestones/M8-live-executors-rev3.md:160-170`,
  `docs/plans/handoffs/M8-subscription-mode-interface-screen.md`,
  `src/constructicon/substrate/executors/codex_protocol.py:11-24`,
  issue #38's 2026-09-12 "Bounded Claude supported-interface screen" comment
