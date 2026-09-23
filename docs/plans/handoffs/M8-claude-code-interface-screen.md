# M8 Claude Code interface screen

Status: credential-free source and documentation screen, 2026-09-22
(America/Los_Angeles). **Every load-bearing citation was re-verified the same
day by a second reader**, who corrected several claims; the corrections are
listed under [Second reading](#second-reading-what-changed). A later review's
verdict corrections are listed under [Review](#review-what-changed). This is not
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
carries it for Codex. The candidate does not qualify as a whole, and no plan
is available at this pin.** Of the ten ADR 0021 requirements screened:

- two are SATISFIED at the source and documentation level: supported direct
  login (R1) and the mode observation (R4);
- three have an **interface affordance found** but remain UNKNOWN as
  requirements: exclusion of alternate credentials (R3), refresh detection
  (R5) and overage surfacing (R6);
- one is NOT SATISFIED for Team and Enterprise subscriptions: cloud-managed
  inputs (R8);
- the remainder are UNKNOWN, each with named resolving evidence.

**Open blocker for every plan (R9).** `EndConversation` cannot be removed while
any other tool remains, and it is not mechanically unreachable. Mapping it to a
non-success outcome is a fail-closed result mapping, not an admitted callback
and not unreachability, which is what ADR 0021 requires of every
model-selectable operation (`0021:103-105`). Every plan, Pro and Max included,
therefore stays unavailable until there is either evidence that
`EndConversation` is unreachable under the fixed launch, or an ADR-backed
treatment of it. This blocker is independent of the plan.

> **Revised 2026-09-23.** A later source reading found that the premise does not
> hold for the fixed `-p` launch. There, `EndConversation` is in the base tool
> collection but is excluded from the active session tool pool by its
> `isEnabled()` gate. That gate needs two things the fixed launch denies:
>
> - a vendor flag, which reads its compiled default `false` while
>   `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` keeps feature-flag fetching off;
> - an entrypoint, which `-p` excludes.
>
> The blocker is **CONDITIONALLY RESOLVED**, pending N6 proof that those
> conditions hold for the whole session. In particular, settings-sourced `env`
> must not be able to reach the process environment, because
> `--setting-sources=` alone does not fence it. An account-empty Windows-build
> observation of 2.1.267 agrees under those conditions: its session pool held
> one MCP callback and no built-in tool. See
> [EndConversation reachability (2026-09-23)](#endconversation-reachability-2026-09-23).

Nothing here was executed, apart from the bounded executions recorded in that
section.

The decisive plan-scoping finding is **server-managed settings**. For a Team or Enterprise
login, Anthropic's servers deliver settings at startup and hourly during the
session. Those settings can carry hooks and environment variables. They outrank
every local source including command-line arguments. In `-p` or Agent SDK runs
they are applied without the approval dialog. The vendor states that you
"can't disable them from the SDK" and that "filesystem isolation does not
remove them". That is exactly the vendor-side widening ADR 0021 forbids
(`0021:267-275`).

At this pin the fetch is gated on the client side: a Pro or Max OAuth login
with no API key is ineligible and makes no fetch. This screen evaluated four
plans: Pro, Max, Team and Enterprise. Of those, **individual Pro and Max are
the only R8 candidates**; Team and Enterprise fail R8. Being an R8 candidate is
not qualifying: Pro and Max still carry R8's own residue and the plan-independent
R9 blocker above. Free, and any plan the pinned mapping does not name, were not
evaluated. They fall outside the adapter's accept rule (R4) and are refused by
that adapter policy, not shown here to be unqualifiable. The R8 narrowing is
within ADR 0021, which already requires every reachable input to be excluded,
fixed or constrained and says a profile that cannot do so cannot qualify
(`0021:267-275`); it narrows the ADR's outcome, which names Claude
subscriptions without a plan. Whether `EndConversation` can be treated without
an ADR amendment is open. The owner should know both before N6 proceeds.

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

**Nothing was executed** in the original screen; the 2026-09-23 section
records one later bounded execution. No Claude binary ran, not even `--version`: the
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
| R3 | Alternate keys, helpers, provider overrides and paid fallback excluded by fixed environment and configuration | `0021:228-230` | **Interface affordance found** (allowlist construction), except R8's input; requirement **UNKNOWN** until the adapter's configuration and fixtures prove it |
| R4 | Supported, non-secret, fresh per-session mode observation before each turn and before acceptance; no model request | `0021:230-236`, `239-240` | **SATISFIED**, with a transport caveat |
| R5 | Refresh cannot silently select API/cloud authentication mid-turn | `0021:236-238` | **Interface affordance found**, as for Codex; requirement **UNKNOWN** until the owed fixture passes |
| R6 | Surface overage facts; `forbidden` needs proved mechanical refusal | `0021:242-254` | Surfacing: **interface affordance found**, requirement **UNKNOWN** until the adapter emits it; `forbidden` **UNKNOWN** |
| R7 | Bounded startup: no model request or account-dependent code before the gate; protocol enforces the phase | `0021:258-265` | **UNKNOWN**: one pre-turn model path found and guarded |
| R8 | Account and cloud-managed inputs excluded, fixed or constrained; vendor-side change cannot widen | `0021:267-275` | **NOT SATISFIED** (Team/Enterprise); **UNKNOWN** (Pro/Max) |
| R9 | Every model-selectable operation is an admitted callback or unreachable | `0021:103-116` | **UNKNOWN**, and an **open blocker for every plan**: interface fits, but `EndConversation` is neither admitted nor unreachable. *2026-09-23: blocker CONDITIONALLY RESOLVED, because the tool is excluded from the active pool under named, fixed conditions that N6 must prove; R9 stays UNKNOWN ([section](#endconversation-reachability-2026-09-23))* |
| R10 | Fixed qualified vendor destinations; no arbitrary proxy/DNS/URL; startup and redirects proved | `0021:277-288` | **UNKNOWN** |

The "SATISFIED" verdicts are interface verdicts in the Codex screen's sense.
They mean the pinned artifact offers what the requirement needs. They do not
mean it was observed working.

**Interface affordance found** is weaker, and this definition covers every use
of it in this screen: the
pinned artifact offers a mechanism the requirement could rest on, but the
requirement is met only by adapter configuration, fixtures or emitted behaviour
that are future work. The requirement itself therefore stays UNKNOWN until that
work proves it.

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

### R3: every identified alternate input is excludable by construction (interface affordance found)

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

That is the affordance, not the requirement. The allowlist, the disposable
`HOME` and configuration directory, and the emptied `settingSources` are adapter
configuration that does not exist yet, so R3 stays UNKNOWN until that
configuration is built and its fixtures show each listed input refused.

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

### R5: an honest mid-turn switch to API authentication would be caught (interface affordance found)

Refresh writes only `claudeAiOauth` (B@181853512). API-key sources come from
the process environment (fixed), settings (sources emptied), `.claude.json`
(disposable), the well-known `/home/claude/.claude/remote/` files (absent) or
server-managed settings (refused plans, R8). A switch that the session
honestly reports adds `apiKeySource` or drops `subscriptionType`, and the
pre-acceptance `initialize` would then refuse the result.

As with Codex, this defends against honest reports only. A client that
misreports its own mode is out of reach (`codex_protocol.py:20-24`). **The N3
analogue owes the fixture**: introduce an API credential mid-turn and prove the
result is refused. Until that fixture passes against the built adapter, R5
stays UNKNOWN.

### R6: overage facts can be surfaced; `forbidden` has no client-side refusal

`rate_limit_event` carries `overageStatus`, `overageDisabledReason`,
`isUsingOverage` and a `credits_required` error code (`sdk.d.ts:4950-4981`).
The experimental `get_usage` control request (`sdk.d.ts:3751`) returns
`extra_usage.is_enabled` (`sdk.d.ts:3847`) without a turn. That is an
interface affordance for surfacing. Surfacing itself stays UNKNOWN: no adapter
decodes these fields yet, and whether the CLI emits them for a given session is
not observed (the companion research records that `rate_limit_event` is
documented as emitted on status change).

Refusal at the included limit is vendor-side. The account's usage-credits
setting ("you can turn usage credits on or off", on claude.ai;
[costs](https://code.claude.com/docs/en/costs)) either lets requests continue
or yields the `credits_required` rejection, which comes from "a claude.ai
subscription whose included usage is exhausted"
([TypeScript reference](https://code.claude.com/docs/en/agent-sdk/typescript)).
The client offers no switch.

`subscription_overage="forbidden"` stays UNKNOWN. A reading of
`extra_usage.is_enabled == false` is observed state, and state alone never
creates a `forbidden` profile. What would resolve it is separately authorized
N5 evidence that the vendor actually refuses at the included limit while that
reading, taken before the turn and again before acceptance, is false. ADR 0021
already says an unproved arrangement makes that profile unavailable
(`0021:247-248`); the alternative is explicitly approved
`operator_authorized` overage (`0021:249-250`).
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
mechanically unreachable, and it is not an admitted callback: it is a vendor
built-in, not one of the adapter's callbacks. ADR 0021 accepts only those two dispositions
for a model-selectable operation (`0021:103-105`). Mapping it to a non-success
outcome is still required as a fail-closed result mapping, but it satisfies
neither. **This is an open blocker for every plan.** R9 stays UNKNOWN, and no
plan is available, until there is evidence that `EndConversation` is
unreachable under the fixed launch or an ADR-backed treatment of it. Its
documented harmlessness is vendor documentation for the current product, not a
qualified property of this pin, and does not substitute for either.

**Pre-turn catalog observation.** `get_context_usage` with
`detail:'summary'`, which avoids token-count API calls (`sdk.d.ts:3631-3635`),
lists `mcpTools`, `systemTools` and `deferredBuiltinTools`. `mcp_status` lists
servers with their `scope`, including `claudeai` (`sdk.d.ts:1117-1156`). The
effective inventory under these flags is UNKNOWN until observed.

**Resolving evidence, credential-free:** an account-empty launch with the fixed
flags, reading both, must list exactly the adapter's callbacks, and at most
`EndConversation` besides. ADR 0021 says a claimed empty inventory proves
nothing (`0021:108`), so this must be observed, not inferred. If
`EndConversation` is listed, the observation confirms the blocker rather than
resolving it; the remaining route is an ADR-backed treatment.

**2026-09-23 correction.** "Cannot be removed while any other tool remains" is
the documented rule for a session whose active tool pool contains the tool.

Under the fixed `-p` launch, `EndConversation` stays in the base collection,
but its `isEnabled()` gate keeps it out of the active pool. The gate needs two
things:

- the vendor flag `tengu_umber_kestrel`, which reads its compiled default
  `false` while `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` keeps feature-flag
  fetching off;
- an entrypoint matching `^cli$`, whereas `-p` forces `sdk-cli`.

The blocker is therefore **CONDITIONALLY RESOLVED**. The conditions have to
hold for the whole session and must be proved in N6. The observation above
must now list **no** `EndConversation`. See
[EndConversation reachability (2026-09-23)](#endconversation-reachability-2026-09-23).

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
the N2 analogue, except that R9's `EndConversation` blocker may need an
ADR-backed decision rather than a test.

## Disposition

**No plan is available at this pin, and this screen does not conclude that no
ADR amendment is needed.** Two consequences need the owner before N6 proceeds:

- **R9, every plan:** `EndConversation` is neither an admitted callback nor
  mechanically unreachable. Every plan stays unavailable until evidence shows it
  unreachable under the fixed launch, or an ADR-backed treatment of it is
  decided. Whether that treatment fits inside ADR 0021 or needs an amendment is
  an owner decision this screen does not make. *(2026-09-23: this is now
  conditionally resolved. The tool is excluded from the active pool under
  named, fixed conditions that N6 must prove. No ADR decision is needed unless
  those conditions cannot be held or the Linux catalog observation contradicts
  the reading; see
  [EndConversation reachability (2026-09-23)](#endconversation-reachability-2026-09-23).)*
- **R8, plan scope:** of the four plans evaluated, **individual Pro and Max
  are the only R8 candidates**. Team and Enterprise are refused by the gate,
  because their cloud-managed settings cannot be excluded. Free and unmapped
  plans were not evaluated; the accept rule refuses them as adapter policy.

The owner decides whether the credential-free N2 analogue, naming repeated
`initialize` as the mode interface, proceeds while the R9 blocker is open. If it
does, it publishes no availability: fake providers exercise the contract
without production availability, and missing mediation proof blocks the
affected adapter (`0021:325-327`, `0021:386-388`).

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
  - map `EndConversation` to a terminal non-success, as a fail-closed result
    mapping only; it does not admit the operation or resolve the R9 blocker;
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

## Review: what changed

An independent review of this screen and its companion research raised
findings that were all accepted. Those touching this screen were corrected here
as wording and verdict changes, with no new research:

- **R9 overstated.** The draft said mapping `EndConversation` to a non-success
  outcome sufficed, that no ADR amendment was needed and that Pro/Max could
  qualify. A fail-closed mapping is neither an admitted callback nor
  unreachability. `EndConversation` is now an open blocker for every plan, and
  Pro/Max are only the R8 candidates.
- **Future work labelled SATISFIED.** R3, R5 and R6's surfacing rested on
  adapter configuration, fixtures and emitted behaviour that do not exist yet.
  They are now "interface affordance found", with the requirement UNKNOWN.
- **`forbidden` from state.** R6 now says an `extra_usage.is_enabled` reading is
  state that never creates a `forbidden` profile by itself, and that the vendor's
  refusal needs separately authorized N5 proof.
- **Plan scope.** The draft refused "every other plan" as if shown
  unqualifiable. Only Pro, Max, Team and Enterprise were evaluated; Free and
  unmapped plans are refused by adapter policy.

## EndConversation reachability (2026-09-23)

This section revisits R9's `EndConversation` blocker. It is a source reading of
the same pinned Linux binary, plus bounded, credential-free executions of the
Windows build of the same version. It changes R9's blocker verdict. It does not
change the other requirements.

**Verdict: CONDITIONALLY RESOLVED.** Under a named, fixed configuration,
`EndConversation` is in the base tool collection but excluded from the active
session tool pool, and so from the model's tool list. It is not "present but
unremovable", and not merely refused. This holds only while the
[conditions below](#conditions-that-must-hold-and-be-proved) hold for the whole
session, and N6 must prove them. It is not an unconditional source-level
resolution. An account-empty Windows-build observation under those conditions
agrees: a session pool of exactly one MCP callback and no built-in tool.

The tool's `isEnabled()` gate requires two things, and the fixed configuration
denies both:

- **A vendor feature flag reading enabled.** While
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` is non-empty in the process
  environment, the flag client is off and the flag returns its compiled
  default, `false`.
- **An entrypoint matching a pattern whose default is `^cli$`.** `-p` forces
  the entrypoint to `sdk-cli`.

The earlier verdict came from the documentation's removal rules. Those rules
apply only to a session whose active pool contains the tool. R9 as a requirement
stays **UNKNOWN**, as before. ADR 0021 says "a denylist or claimed empty
inventory alone proves neither property" (`0021:107-108`). Absence was
therefore observed here on the Windows build, and must still be observed on the
qualified Linux pin in the catalog test R9 already owes. That test must now
show **no** `EndConversation`, not "at most `EndConversation`". If it does show
the tool, this reading is wrong and the blocker returns (see
[Fallback](#fallback-if-the-observation-contradicts-this-reading)).

Evidence base:

- Tarball integrity was re-verified against `npm view … dist.integrity` for the
  wrapper, `linux-x64` and the SDK, identical to the table under
  [Pins](#pins-and-evidence-boundary).
- The Linux binary SHA-256 is `0399c793…403c0`, unchanged.
- `@anthropic-ai/claude-code-win32-x64@2.1.267` has integrity
  `sha512-NQPJdlwcfPLVapMQE/C3SzgNX29qRuQPKy7hVwgrDCOr4Wfd3IlYVibk+VCeLbInUNSQJ4GpE9niSp9YeSRf6w==`,
  reproduced locally. Its `claude.exe` SHA-256 is
  `23dde2a47cf1d7d9c4a2d96d21fa80ea9bfc872dfde0ee06e9982d2908603350`, which
  equals the SDK `manifest.json` `win32-x64` checksum.
- Documentation was re-fetched with `curl` as raw Markdown at 2026-09-23T06:39Z.
  `tools-reference.md` is byte-identical to the 2026-09-22 copy.

B@offsets are into the Linux binary. Cross-chunk names were resolved by
export-set match as before; every match below was unique.

### What admits the tool to the active pool

1. **The pool filter.** The base tool collection `hx()` always includes
   `EndConversationTool` (B@187738313, B@187740245), so the tool is
   constructed in every session. The main pool builder removes every tool whose
   `isEnabled()` is false, after the permission-rule filter:
   `let k=d.map((P)=>P.isEnabled()),v=d.filter((P,O)=>k[O]);` (B@187741327,
   inside `ZA` at B@187740597). The tool's own
   `isEnabled(){let e=_2e();return e!==void 0&&G1t(e)}` is at B@198610257.
2. **The predicate** `G1t` (B@197445986) is exported as
   `isEndConversationToolEnabled`:

   ```js
   function G1t(e){let t=UL();if(t===void 0)return!1;if(!r(e))return!1;
     let{enabled:o,allowedEntrypoints:s}=l(I(qIn,!1));if(JEt())return!1;
     return o&&s.test(t)}
   ```

   - `qIn="tengu_umber_kestrel"` (B@182736125) is the flag.
   - `I(e,n)` reads the GrowthBook value with default `n=false` (B@181715833).
   - `l()` maps `true` to `{enabled, allowedEntrypoints:/^cli$/i}`, an object
     to a pattern built from its `scope`, and anything else to
     `enabled:false` (B@197445632 onward).
   - `r(e)` is a model-family floor, `opus ≥ 4.8`, `sonnet ≥ 5`, `fable ≥ 5`,
     `mythos ≥ 5` (B@197445539), through `Tje` (B@182193800).
   - `JEt()` is `return!1` (B@183734126).
3. **The entrypoint.** `UL()` returns the session entrypoint (B@179453300). At
   startup, `si()` passes `O = non-interactive` into `abr(O)`, which calls the
   setter `S(e)` (B@193298630). `O` is true for `-p`/`--print` and for any
   non-TTY stdout (`zmr`, B@180762971). `S(e)` does two things:
   - if `CLAUDE_CODE_ENTRYPOINT` is unset, it sets it to
     `e?"sdk-cli":"cli"` (B@179454629);
   - if the variable is `"cli"` in a non-interactive run, it rewrites it to
     `"sdk-cli"` (B@179454324).

   A `-p` session therefore never has entrypoint `cli`. The default pattern
   `^cli$` rejects it, **even when the flag is simply `true`**. Only a flag
   *object* whose `scope` matches `sdk-cli`, or an entrypoint variable the
   allowlist would have to supply, gets past this gate.
4. **The flag under the fixed environment.** Three facts decide it:
   - `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` makes the privacy level
     `"essential-traffic"` (B@179247012). That makes `iU()` true
     (B@179247277), `Fg()` true (B@181197148), `wM()` false (B@181708708)
     and the GrowthBook `isEnabled` `j4()` false (B@181714139; wired at
     B@181713148).
   - `getFeatureValueWithSource` checks environment overrides first. They
     are `getEnvironmentOverrides(){return null}` (B@181173409). Config
     overrides are next, and they are `readConfigOverrides(){return}`
     (B@181173836). Then it returns `{value:n,source:"disabled"}`
     **before** reading any fetched payload or disk cache (B@181181177).
   - The only way back to the disk cache is
     `CLAUDE_CODE_GB_DISK_CACHE_WHEN_TELEMETRY_OFF` (B@181714187), a
     variable the allowlist does not supply.

   So, while the variable is present, the flag reads `false`, `l(false)` is
   `enabled:false`, and the tool is not in the active pool. The model-family
   floor does not help, because the models the adapter would pin all pass it.
   Both the GrowthBook `isEnabled` check and the pool filter read the
   environment each time they run, not once at startup. The session tool
   function additionally caches its result for up to 30 s (`Lp=30000`,
   B@201058846). If the variable were lost mid-session, a later read would no
   longer be forced to the default. Whether and when a fetch would then run
   was not traced. That is why the conditions below must hold for the whole
   session.
5. **No fallback dispatch.** A call naming a tool that is not in the session
   pool is looked up in the full base list only when the name is an **alias**
   of a base tool: `if(!y){let be=cr(hx(),p);if(be&&be.aliases?.includes(p))y=be}`
   (B@187786933). `EndConversation` declares no aliases. Its definition is at
   B@198609929, and the builder defaults are at B@182160149. An invented call
   therefore takes the `unknown_tool` / "No such tool available" path
   (B@187777272).

The Windows build carries the same predicate under different minified names:
`let{enabled:o,allowedEntrypoints:s}=l(P(XPn,!1))` (W@201654952) and
`="EndConversation",XPn="tengu_umber_kestrel"` (W@186847300). W@ offsets are
into the Windows `claude.exe`. It also carries byte-identical
text for the entrypoint setter, the privacy level, the null overrides and the
`"disabled"` branch. That is a textual comparison, not a proof that the builds
behave the same.

The documentation agrees at the surface level. The tool "appears only when all
of the following are true", including "**Surface**: an interactive terminal
session". It lists "non-interactive `-p` runs" and "sessions through the Agent
SDK TypeScript and Python packages" among surfaces that "don't include the
tool"
([tools reference](https://code.claude.com/docs/en/tools-reference),
`tools-reference.md:248-254`). The source adds what the documentation leaves
out: that exclusion is the **default scope of a vendor-served flag**, and the
vendor could widen it. The same page says flag fetching is off under
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, which "Also disables feature-flag
fetching" ([environment variables](https://code.claude.com/docs/en/env-vars)).
The listing of variables that skip the fetch covers "`DISABLE_GROWTHBOOK`,
`DISABLE_TELEMETRY`, `DO_NOT_TRACK`, or `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`".
The flag is a cloud-managed input in `0021:267-275`'s sense. The requirement
that "a vendor-side account/scope or configuration change cannot enable
additional native tools" (`0021:270-272`) is therefore met only while the
environment variable that pins the flag to its compiled default is itself
fenced from every settings input. The next subsection shows that
`--setting-sources=` alone does not fence it.

### Conditions that must hold and be proved

**Settings reach the process environment by a path `--setting-sources=` does
not close.**

- `applyConfigEnvironmentVariables` assigns the global configuration's `env`,
  from `.claude.json` via `ne().env`, into `process.env`. It then does the
  same for every *enabled* settings source (B@181944710):

  ```js
  this.appliedGlobalConfigEnv=this.filterSettingsEnv(ne().env,"globalConfig"),
  Object.assign(process.env,this.appliedGlobalConfigEnv);
  for(let A of Wo())Object.assign(process.env,this.filterSettingsEnv(ye(A)?.env,A));
  ```

- `Wo()` always adds `flagSettings` and `policySettings` to the sources that
  `--setting-sources` allows (B@179746499).
- The environment filter `filterSettingsEnv` (B@181940296) contains no rule
  naming `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`: a targeted search of its
  chunk found no such literal. Its six generic stages were not traced, so it
  may or may not drop such a value.
- The remote-settings refresh re-applies the environment after a policy change
  (B@192064048).

Unless one of those stages removes it, a settings `env` entry could set the
variable to an empty string, which the privacy-level test
`if(process.env.CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC)` (B@179247012) reads
as unset. That would re-enable GrowthBook and hand the
flag, and with it the entrypoint `scope`, back to the vendor.

The verdict holds only under all of the following. N6 must prove each for the
qualified Linux pin, for the whole session:

1. **Process environment.** The allowlist supplies a non-empty
   `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` and never supplies
   `CLAUDE_CODE_GB_DISK_CACHE_WHEN_TELEMETRY_OFF` or `CLAUDE_CODE_ENTRYPOINT`.
   The launch is `-p`.
2. **Global configuration.** `.claude.json` in the disposable configuration
   directory starts fresh and has no `env` key. Its `env` is applied
   regardless of `--setting-sources`. This joins R2's open question about a
   fresh `.claude.json`.
3. **`flagSettings`.** There is no `--settings` argument. The host never sends
   the settings-changing control requests, `apply_flag_settings` or
   `update_settings` (`sdk.d.ts`, `SDKControlRequestInner`). Like the other
   host requests, they are never model-selectable.
4. **`policySettings`, local.** There is no managed-settings file or
   endpoint-managed policy in the native zone, whose `/etc` and home are
   adapter-constructed. This is an existing N3 layout obligation.
5. **`policySettings`, server-managed.** No server-managed settings are
   delivered. At this pin a Pro or Max OAuth login without an API key is
   ineligible for the fetch (`unsupported_subscription`, see R8, B@181929706).
   That is source-level only: **whether a Pro/Max binding ever receives
   server-managed settings at this pin is UNKNOWN until N4 observes no fetch
   for the provisioned binding.** Team and Enterprise are already refused by R8.
6. **Same binary.** The flag name, its default scope, the entrypoint rewrite and
   the settings-to-environment path are all facts of this pin.

If any condition cannot be held and proved, the blocker returns (see
[Fallback](#fallback-if-the-observation-contradicts-this-reading)).

### Per mechanism

| Mechanism | Verdict | Evidence |
| --- | --- | --- |
| `isEnabled()` gate: `-p` entrypoint plus `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | **(a) Excluded from the active pool, conditionally.** Either condition alone keeps the tool out at the defaults. The environment condition is the one a vendor flag change cannot reverse, but only while the environment is fenced from settings (conditions 1–6) | Items 1–5 and the conditions above |
| `DISABLE_GROWTHBOOK=1` | **(a)**, redundant: it also makes `j4()` false (B@181714139). Optional; not needed at this pin | Source; `env-vars.md:425` |
| `--tools ""` or a `--tools` list | **Not a removal mechanism** for this tool while any other tool remains. Moot under the fixed configuration, where `isEnabled()` excludes the tool from the active pool | "neither `--disallowedTools` nor a `--tools` list can remove it" (`tools-reference.md:244`) |
| `--disallowedTools EndConversation` | **Ineffective while other tools remain.** Deny lookups skip the tool: `ip=new Set([…END_CONVERSATION_TOOL_NAME])` (B@182515712), `Get(e)` (B@182515807), `hi()` returns `null` for it (B@182517379), and ask rules do the same (`Pm`, B@182518021). Removal happens only when everything else is gone too (`zcr`, B@182517535) | `cli-reference.md:84`; `permissions.md:58` |
| settings `permissions.deny` | **Ineffective**, the same code path | `settings-reference.md:1521` |
| PreToolUse hook that denies | **Ineffective.** "PreToolUse also doesn't fire for `EndConversation`" | `hooks.md:1594`, `hooks.md:23`, `hooks.md:1908` |
| `--permission-prompt-tool` / SDK `canUseTool` | **Ineffective.** The tool "never prompts for permission". It inherits the builder's default `checkPermissions` result, `{behavior:"allow"}` (B@182160149), so no prompt handler is consulted | `tools-reference.md:244`; `hooks.md:1908` |
| MCP-only catalog (`--tools ""` plus SDK MCP callbacks) | **Not a removal mechanism.** The callbacks are "other tools", which is the condition under which deny rules leave the tool alone | `tools-reference.md:244` |
| `--bare` / `CLAUDE_CODE_SIMPLE` | **(a) Absent**, since the simple-mode branch returns a fixed list (B@187740597). **Unusable**: bare mode does not read OAuth (see Considered and rejected) | `tools-reference.md:257` |
| Model choice below the family floor | **(a) Absent**, but it would constrain the model inventory to older models. Rejected | B@197445539 |

**(b), "present but every invocation refused", has no instance for this tool.**
Every refusal mechanism above is documented, and for deny rules also
source-shown, to skip it. The question is still recorded, since it recurs for
other built-ins. ADR 0021 says: "Every model-selectable operation must be an
admitted callback or mechanically unreachable. … a denylist or claimed empty
inventory alone proves neither property" (`0021:103-108`).

- *For* treating a refused tool as unreachable: the ADR speaks of
  *operations*. If every path from selection to effect is cut before any
  effect, the operation cannot be reached, even though its name is visible.
- *Against*: a per-call refusal is a denylist evaluated by vendor code, which
  is the case `0021:107-108` names. The model can still *select* the tool, so
  it is model-selectable. Proposed ADR 0020, which is not accepted and is
  cited here only for its wording of the same law, requires the catalog to
  contain "exactly the admitted callback tool set", with everything else
  "absent or mechanically unreachable", and says "A configuration flag or empty
  list alone is not that proof" (`0020:104-111`).

**This is an open owner/ADR interpretation, not a finding.** This section's
reading is that a present-but-refused built-in is not "mechanically
unreachable" in ADR 0021's sense unless the refusal is itself a qualified,
uniform mechanism proved by fixture, and that a permission rule or hook does
not qualify. ADR 0021 does not settle the general proposition: `0021:107-108`
says only that a denylist or claimed empty inventory *alone* proves neither
property, and ADR 0020's wording is from a proposal that was not accepted.

The verdict above does **not** rest on this reading. It rests on case (a),
exclusion from the active pool, under the stated conditions. If a future pin or
tool depends on case (b), the owner decides the interpretation.

### What the tool does

From its definition (B@198609929 to B@198611356):

- **In a fork or subagent:** it returns a "does nothing here" message
  (B@198610631).
- **First call:** unless the previous assistant turn already called it, it
  returns a "re-read the guidance … call again" message with no effect
  (B@198610774).
- **Second consecutive call:**
  - it logs the analytics event `tengu_end_conversation_tool_call`;
  - it appends an `{type:"ended-by-model"}` marker to the session transcript
    through `cEn` (B@189518602). `cEn` returns early when session persistence
    is disabled, because `kl()` (B@189432243) includes `XL()`,
    `sessionPersistenceDisabled` (B@179002408);
  - it calls `endTurn("end_conversation")` (B@198611105). That is the turn
    context's `endTurn:(o)=>e.abortController.abort(o)` (B@182158793), so it
    **aborts the in-flight turn** with reason `end_conversation`;
  - in a non-interactive session it calls `gracefulShutdown(1,"other",…)`
    (B@198611219). The shutdown path (B@189595800 onward) does all of the
    following:
    - sets `process.exitCode=1` and arms a failsafe timer;
    - prints a resume hint;
    - runs several internal cleanup steps, not individually traced;
    - **executes any configured SessionEnd hooks**, with a timeout;
    - emits `session_end`;
    - **waits for any in-flight OAuth refresh to finish**;
    - writes the final message to stderr and drains stdout;
    - **forces process exit**.

So its effect is **self-termination of the session and process**, not only an
exit code. That covers:

- the abort of the running turn;
- the shutdown sequence above, including whatever cleanup and SessionEnd hooks
  are configured;
- a transcript append inside the disposable configuration directory, unless
  persistence is disabled;
- an analytics event.

Under the fixed configuration no hooks are configured: settings sources are
emptied, and `initialize` carries none. The shutdown's wait for a held OAuth
refresh is store custody that R2 and N3 already own. No workspace or credential
authority was found in this path. The shutdown's untraced cleanup steps bound
that claim.

The documentation says it "does nothing except end the conversation, never
reading or modifying files or data" (`tools-reference.md:244`). The source shows
that "end the conversation" includes a full process shutdown. It is still a
model-selectable *operation* in ADR 0021's list-based sense: it changes session
state and process lifecycle, and the ADR has no harmlessness exception. Its effect is a subset of what the
adapter must already treat as failure (`0021:124-125`: nothing "may become
success because the CLI said so"), which is why an ADR-backed treatment would be
narrow if one were ever needed.

### What was executed

The pinned version's Windows build was run three times, each time with a new
fresh scratch root. The second and third runs were separately approved by the
lead. Every run had the same conditions:

- a fresh empty scratch root, with `HOME`, `USERPROFILE`,
  `CLAUDE_CONFIG_DIR`, `APPDATA`, `LOCALAPPDATA`, `TEMP` and `TMP` pointing
  into it;
- an environment built from scratch with only those variables plus
  `SYSTEMROOT`, `WINDIR`, `PATH=%SYSTEMROOT%\System32`,
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`,
  `ENABLE_CLAUDEAI_MCP_SERVERS=false` and `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`;
- no `ANTHROPIC_*` variables, in the child or in the parent shell.

The Windows Credential Manager store is consulted only under
`CLAUDE_CODE_FORCE_WINDOWS_CREDMAN=1` or a cached flag in a config file. Both
are absent from a fresh directory; see the Windows build's
`cachedGrowthBookFeatures?.tengu_windows_credman===!0` reader (W@184974356).

Common arguments:
`-p --input-format stream-json --output-format stream-json --verbose --tools ""
--strict-mcp-config --setting-sources= --disable-slash-commands
--no-session-persistence --mcp-config <file>`.

**Run 1: `initialize` only, with no MCP server.** The configuration was
`--mcp-config {"mcpServers": {}}`. The only input was
`{"type":"control_request","request_id":"init-1","request":{"subtype":"initialize"}}`.
Fifteen seconds later the process was still running (`poll()` = `None`) and was
killed. It printed exactly one line, the `initialize` success response, which
included:

```json
"account":{"tokenSource":"none","apiProvider":"firstParty"}, …
"analytics_disabled":true, … "session_state":"idle"
```

It also carried `commands:[]`, the built-in agents, output styles and models.
It carried **no tool list**: `SDKControlInitializeResponse` has no tools field
(`sdk.d.ts:4052-4062`), and `system/init`, which carries `tools`
(B@192873678), is emitted "at the start of each turn" (`sdk.d.ts:5172-5173`). A
turn needs a user message, which these bounds forbid.

**Run 1 therefore did not observe the catalog.**

**Runs 2 and 3: one SDK MCP server and one `get_context_usage`.** The
configuration file was `{"mcpServers": {"cb": {"type": "sdk", "name": "cb"}}}`.
The first input was:

```json
{"type":"control_request","request_id":"init-1","request":{"subtype":"initialize","sdkMcpServers":["cb"]}}
```

The CLI then sent three `mcp_message` control requests, and the harness
answered each:

1. `initialize`, with protocol `2025-11-25` and client `claude-code` version
   `2.1.267`, answered with a `tools` capability;
2. `notifications/initialized`, answered with an empty success;
3. `tools/list`, answered with one inert tool:
   `probe_callback`, with the empty object schema.

**No `tools/call` arrived.** Fifteen seconds after `initialize` the harness sent
exactly one
`{"type":"control_request","request_id":"ctx-1","request":{"subtype":"get_context_usage","detail":"summary"}}`,
waited fifteen seconds and killed the process, which was still running. Stderr
was empty. No output mentioned an API call, login, authentication or fetch.

**Run 2 is discarded.** The harness truncated each stdout line at 4000
characters, which cut the response before its tool fields. Run 3 repeated it
exactly, capturing every line in full. The run 3 `ctx-1` response, verbatim
except that the `gridRows` display array is omitted:

```json
{"categories":[{"name":"System prompt","tokens":2422,"color":"promptBorder"},
 {"name":"MCP tools","tokens":74,"color":"cyan_FOR_SUBAGENTS_ONLY"},
 {"name":"Autocompact buffer","tokens":33000,"color":"inactive"},
 {"name":"Free space","tokens":964504,"color":"promptBorder"}],
 "totalTokens":2496,"maxTokens":1000000,"rawMaxTokens":1000000,
 "autocompactSource":"model-default","percentage":0,"model":"claude-opus-5[1m]",
 "memoryFiles":[],
 "mcpTools":[{"name":"mcp__cb__probe_callback","serverName":"cb","tokens":74,"isLoaded":false}],
 "agents":[],"autoCompactThreshold":967000,"isAutoCompactEnabled":true,
 "messageBreakdown":{"toolCallTokens":0,"toolResultTokens":0,"attachmentTokens":0,
  "assistantMessageTokens":0,"userMessageTokens":0,"redirectedContextTokens":0,
  "unattributedTokens":0,"toolCallsByType":[],"attachmentsByType":[]},
 "apiUsage":null}
```

The observed tool list is exactly **`mcpTools = [mcp__cb__probe_callback]`**.
The keys `systemTools` and `deferredBuiltinTools` are absent, not empty. At
this pin the builder hard-codes both to `void 0`
(`deferredBuiltinTools:void 0,systemTools:void 0`, B@187762178), so built-in
tools appear only as aggregate categories:

- `"System tools"`, pushed when the non-deferred built-in token count is
  positive (B@187759148);
- `"System tools (deferred)"`, pushed when the deferred built-in token count is
  positive (B@187759148).

Those counts come from `eas`, which returns zero for both when the pool holds
no non-MCP tool (B@187750960). **Neither category is present, so the session
pool holds no built-in tool, deferred or not.** That includes `EndConversation`,
which is a deferred tool (`shouldDefer:!0`, B@198609929). Its description, a
multi-paragraph guidance text, would have produced a non-zero category.
The pool counted is the stream-json session's own tool function `_i`
(B@201122297), which builds through `nD`, and so through `ZA` (B@201058846).

**What the observation covers:**

- the Windows build of 2.1.267, not the Linux pin;
- `-p` with the `sdk-cli` entrypoint;
- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, so GrowthBook is off and the
  flag reads its default;
- no credentials;
- default model `claude-opus-5[1m]`, which by the source reading passes the
  model-family floor;
- `--tools ""` and one SDK MCP callback.

**What it does not cover:**

- a GrowthBook-enabled session, where the vendor flag value could arrive;
- a session with the `cli` entrypoint, meaning interactive or with that
  variable set;
- an authenticated session;
- a later turn;
- the Linux binary.

It also cannot say *which* failed condition removed the tool. That attribution
rests on the source reading above.

One incidental observation for the N2 analogue: the callback is reported
`isLoaded:false`, although no built-in `ToolSearch` is in the pool. How a
deferred MCP callback is presented to the model on the first turn is not
established here.

After each run the fresh configuration directory held `.claude.json`, one
backup of it, `.last-cleanup`, and `sessions/<pid>.json` with a `.key` file.
That is a live-session registry, not a transcript. No login, credential, model
call or user message was involved in any run.

### Resulting R9 status

- **EndConversation: CONDITIONALLY RESOLVED, pending N6 proof of conditions
  1–6.** Under that fixed configuration the tool is excluded from the active
  session tool pool by its `isEnabled()` gate, which is case (a). The gate
  needs a vendor flag, held at its compiled default `false` while
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` is in the environment, and an
  interactive entrypoint, which `-p` excludes. The account-empty Windows-build
  observation (run 3) agrees for that configuration: a pool of exactly one MCP
  callback, and no built-in tool, deferred or not.
  - No ADR amendment is needed **if** the conditions are proved.
  - The owner question the screen raised returns if any condition cannot be
    held, notably if a Pro/Max binding receives server-managed settings
    (condition 5), or if the Linux observation contradicts this reading.
- **R9 overall: UNKNOWN, unchanged.** The full catalog requirement is still
  owed on the qualified Linux pin: an account-empty launch with the fixed flags
  and the adapter's real callback server must list exactly the callbacks and
  **no** `EndConversation`. That observation can be read with
  `get_context_usage` (`detail:"summary"`, which "answers from the last
  response's usage and local estimates without the per-category token-count
  calls", `sdk.d.ts:3630-3636`) exactly as in run 3. The adapter's first-turn
  `system/init` `tools` list corroborates it. The rest of R9 is untouched by
  this section.

Obligations this adds to the N2 analogue:

- `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` is now **load-bearing for R9**, not
  only for egress. The environment fixture must prove conditions 1–3:
  - the variable is present and non-empty;
  - `CLAUDE_CODE_GB_DISK_CACHE_WHEN_TELEMETRY_OFF` and
    `CLAUDE_CODE_ENTRYPOINT` are absent;
  - `.claude.json` carries no `env`;
  - there is no `--settings` argument, and no `apply_flag_settings` or
    `update_settings` control request is ever sent.
- N3 owns condition 4, keeping managed-settings paths out of the native zone,
  and N4 owns condition 5, observing no settings fetch for the Pro/Max binding.
- The catalog test asserts the exact callback set, with `EndConversation`
  absent.
- The fail-closed mapping of an `end_conversation` stop or exit code 1 to a
  terminal non-success stays, as general failure mapping. It no longer stands
  in for R9.
- A changed binary re-reads this predicate and the settings-to-environment
  path. The flag name, default scope and entrypoint rewrite are all
  pinned-version facts.

### Fallback if the observation contradicts this reading

The blocker returns as **NEEDS OWNER/ADR DECISION** in either of two cases:

- the Linux catalog observation lists `EndConversation`;
- a condition in [Conditions that must hold and be proved](#conditions-that-must-hold-and-be-proved)
  cannot be held and proved.

The question for the owner: may a vendor safeguard tool whose effect is
terminating its own turn and process, mapped to a terminal non-success, be
admitted under ADR 0021 as a third disposition beside "admitted callback" and
"mechanically unreachable"? The options:

1. Amend ADR 0021 narrowly for self-terminating built-ins with no workspace,
   store, network or persistent authority, proved per pin. That proof includes
   the shutdown path's cleanup, SessionEnd hooks and OAuth-refresh wait.
2. Keep Claude Code unavailable under v3.
3. Wait for a pin whose active-pool exclusion can be shown without these
   conditions.

### Limits of this section

- The source reading is of a minified bundle. The claim that no other path
  registers or dispatches the tool rests on targeted searches:
  - every chunk importing the name constant (six) was read at its use sites;
  - the re-exported name is used at four sites (the deny set, the abort
    classifier, the deferred-tool hint and the renderer table);
  - every call site of the base list `hx()` in its chunk was read:
    - the `--tools` narrowing and permission-map builders;
    - the enabled-name and code-execution sets;
    - the pool builder `ZA`;
    - two unknown-tool message builders;
    - the alias fallback, which is the only one that dispatches.

    Two other chunks import `hx`. One resolves a teammate's inbox permission
    request by name (B@204694478). The other is a UI confirmation preview
    (B@204883652). Neither dispatches a tool call.

  That is not an exhaustive proof.
- Environment mutation is bounded by what was found: the
  settings-to-environment path (B@181944710) and the entrypoint setter. The
  first draft of this section said no runtime write to
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` was found. That was wrong: a
  literal search misses the generic `Object.assign(process.env, …)`. Another
  generic path may exist, which is why conditions 1–6 must be proved by
  fixture rather than inferred.
- The shutdown path's internal cleanup steps (B@189595800 onward) were not
  individually traced.
- The execution used the Windows build, not the Linux pin. It covers only the
  configuration listed under [What was executed](#what-was-executed).
- **Review.** One Codex pass (job `job_92d8fbf9d224`) attacked the first draft.
  Its findings were reproduced against the binary and accepted:
  - "RESOLVED" was overclaimed, given the settings-to-environment path;
  - the effect inventory was incomplete: turn abort and full shutdown;
  - "never registered" was inexact, since the tool is present in the base
    collection and excluded from the active pool;
  - the case (b) reading is an interpretation, not support for the verdict.

  Its supporting claim that ToolSearch draws on the gated pool (B@186426900)
  could not be confirmed at that offset and is not relied on.

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
