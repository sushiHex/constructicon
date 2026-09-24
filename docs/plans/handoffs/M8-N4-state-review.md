# M8 N4: authenticated startup, state and resume review

Status: pre-implementation design, independently reviewed once (Codex
`gpt-5.6-terra`, effort high, job `job_874f14f36992`, at `a2b2004`, verdict "do
not implement") and amended. Every premise was reproduced against source first.
The dispositions are under [Review disposition](#review-disposition). By
instruction there is one review pass, so these amendments have not been
re-reviewed.
Base: `main` at `9006f93`. Branch: `m8/n4-startup`.
Scope: N4 of [issue 77](https://github.com/sushiHex/constructicon/issues/77),
private authenticated startup for Codex. This covers everything that can be
built and proved credential-free, plus a runbook for the one operator-attended
login session.
Authority:
- [M8 rev 3, N4](../milestones/M8-live-executors-rev3.md) lines 118-140 (frozen, not edited).
- [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md):
  - lines 186-204: maintenance and activation;
  - lines 206-254: vendor-owned authentication, mode and overage;
  - lines 256-287: non-widening and egress.
- [ADR 0020](../../adr/0020-native-harnesses-mediate-contained-tools.md):
  - lines 155-264: credential lifecycle and the startup phase;
  - lines 266-302: vendor-session egress.
- The owner's N4 authorization on #77 fixes the startup methods: `initialize`,
  `initialized`, `account/read` and `account/rateLimits/read`. It permits no
  `turn/start` and no model request.
- The owner's N5 authorization on #78 fixes the overage bound that the readback
  has to serve.

This document amends none of these sources.

No implementation code exists for anything below. Every test named here is a
design obligation, not a claim about an executed test.

Pinned source is `openai/codex` tag `rust-v0.153.4`, commit `3d2ee51`. Paths
are relative to `codex-rs/`. It was read from a local checkout of that exact
commit.
- Rows marked "(trace)" come from a delegated source trace. Each one is a
  claim and gets reproduced before any code relies on it.
- Every other pinned citation was read directly for this document.

## The design in brief

1. **Narrow layout, bound by descriptor.** The native zone's `CODEX_HOME` is a
   fresh tmpfs directory. Exactly two things in it come from outside the zone:
   - the sealed configuration, from a sealed memfd, read-only;
   - the store's `auth.json`, bound read/write as a single file, through the
     descriptor that was checked.

   Everything else the client writes there dies with the namespace. The store
   directory is no longer mounted. Today nothing delivers the
   sealed configuration to the client, and nothing routes the credential to
   it (Inputs, rows 1 and 2). N4 cannot start without both.
2. **One conversation, one boundary.** The existing conversation gains an
   `account/rateLimits/read` readback:
   - once after the pre-turn mode gate, before `thread/start`;
   - once after the pre-acceptance reading.

   N4's startup lane is the same conversation, stopped right after the first
   readback. It never sends `thread/start`, so it makes exactly the four
   authorized requests.
3. **The readback is judged, not just recorded.** It reads the Codex bucket by
   its limit id and refuses when that bucket is absent. Before the turn, that
   bucket must show the plan the binding expects and no purchased credits,
   which is the owner's N5 bound, written as code. After the turn, its overage fields must equal the
   pre-turn values. The post-turn reading becomes the outcome's `rate_limit`.
   Only a fixed set of numeric and boolean fields is published; account ID,
   plan and upsell are never published.
4. **Account notifications move from a namespace to an allowlist.** The pin
   emits exactly three `account/` notifications. Only
   `account/rateLimits/updated` is admitted, and only when its `planType` is
   absent or equals the expected plan. Every other `account/` method still
   refuses, and so does the whole `modelProvider/` namespace (auth recovery).
5. **The relay records per sealed destination.** For each sealed destination
   it records how many connections were accepted and how many relayed at least
   one upstream byte. Denials stay counted by reason only, so an attempted
   hostname is never retained. The sealed configuration disables every
   default-on auxiliary network feature. A clean startup therefore shows zero
   denials, and a same-run control shows that the counter counts.
6. **Launches held under maintenance.** The maintenance context exposes its
   lock and one positive check. The operator's login, and the qualification
   startup run just after it, both run in the real zone behind the relay while
   the maintenance lock is held, before the next generation is published. The
   floor from N3c makes a later re-login invalidate that run mechanically.
   That activation *follows* a completed qualification remains operator input
   (N3c decision 3), and is not claimed here. The conformance revision is the
   digest of the evidence file, so the sealed identity at least names the
   evidence it rests on.
7. **One operator lane module.** It holds the `login` and `startup`
   compositions of existing parts. It writes bounded evidence, marked
   `completed` only as its last act.

The design adds no L0 field, journal record, service, walker change or
selector.

## Scope: issue 77's acceptance criteria

| # | Criterion (#77) | Design | Credential-free proof | Operator evidence |
| --- | --- | --- | --- | --- |
| 1 | Written operator authorization linked before any authenticated activity | Already linked (the owner's authorization comment on #77). The runbook's step 0 re-checks the listed preconditions and stops if any is missing | None needed | Precondition checklist with links, recorded in the PR |
| 2 | Every authority input is excluded, fixed and revision-bound, or enforced before use, including during refresh. Configuration, tool and egress confinement are proved independently of account identity | Design 1 (layout), 8 (inventory) and 3 (the mode-bearing notification). Refresh stays in place in the one bound file | L1 (layout), L2 (production configuration: no auxiliary CONNECT, with a control run), P5, P6 | S4 and S8 startup evidence: methods sent, per-destination relay record, gate and readback verdicts |
| 3 | Rev 2 N4's authenticated positive controls are kept, except the principal/scope comparison, which binding/layout/mode refusal replaces. Missing identity is recorded as unverified | See the [positive-control table](#positive-controls-kept-from-rev-2-n4) | L2 (absent account), L3 (login egress), P6 (expired login is refused by the readback) | S3-S10, each run labelled with the control it serves |
| 4 | Only bounded, non-secret observations. No vendor identity in public telemetry. Zero spend is never inferred from a mode flag or tier | Design 2 publishes a fixed vocabulary. The evidence schema is closed. Spend is judged only from fields that are present; an absent credits object refuses | P4 and P9 (field walks with planted identity values), P2 (absence refuses) | The evidence JSON itself |
| 5 | An unsafe or unavailable positive control leaves the profile unqualified | Every control has a measured/unmeasured row. `vendor_conformance_qualified` stays false until each row is measured, and refresh counts as a required control | P9 (a lane with no refresh reports "unmeasured", never "passed") | S10 refresh run. Until it is measured, the profile stays unqualified |

## Inputs checked against source

Repository citations are at `9006f93`.

1. **The sealed configuration never reaches the client.**
   - `CodexOperatorProvider` digests `configuration` and keeps only
     `configured_model` from it (`codex.py:1797, 1851`).
   - The command is `app-server --strict-config --stdio` (`codex.py:165`) with
     `HOME=/tmp/home` on a tmpfs (`linux.py:331-334`).
   - Only the test bootstrap writes `/tmp/home/.codex/config.toml`
     (`tests/substrate/_native_startup_bootstrap.py:20-22`).
   - In production, the client would therefore run on built-in defaults: plugins
     on, a remote models list, analytics on. The launch identity would still
     claim a configuration digest.
2. **The store is mounted, but the client never reads it.**
   - The store directory is bound at `/vendor-store` (`linux.py:342`), and no
     `CODEX_HOME` is set.
   - The pinned client's file backend reads and writes exactly
     `codex_home/auth.json` (`login/src/auth/storage.rs:154-156`).
   - `codex_home` defaults to `$HOME/.codex`. That is the disposable tmpfs, so a
     real login would never be found.
   - The N3c limit "the layout N4 chooses must not make the writable store a
     configuration root" names this gap.
3. **Pinned saves are in place.**
   - `FileAuthStorage::save` opens `auth.json` with truncate, write and create,
     mode `0600` on creation, and never renames (`storage.rs:206-222`).
   - Logout removes the file (`storage.rs:158-164`).
   - Login first runs `logout_with_revoke` and only warns if that fails
     (`cli/src/login.rs:122-138`; `login/src/auth/manager.rs:951-976`).
   - A single-file bind therefore supports both refresh and login. Removing the
     file fails with `EBUSY` and is ignored (to be proved by L1 and L3). No zone
     can replace the bound file.
4. **Account notifications at the pin** (generated
   `app-server-protocol/schema/json/ServerNotification.json`):
   - `account/updated`, lines 7596-7610. Its params are
     `{authMode, planType}` (`v2/account.rs:545-548`). The app-server emits it
     after login and logout (`app-server/src/request_processors/account_processor.rs:903, 948, 1013`).
   - `account/rateLimits/updated`, lines 7616-7630. Its params are
     `{rateLimits: RateLimitSnapshot}` (`v2/account.rs:558-561`), and the
     snapshot has `planType` (`:565-575`). It is emitted on every token-count
     event that carries rate limits, meaning during a turn
     (`app-server/src/bespoke_event_handling.rs:1676-1701`).
   - `account/login/completed`, lines 8318-8332. Its params are
     `{loginId, success, error, onboardingEntrypoint}` (`v2/account.rs:712-718`),
     emitted by login (`account_processor.rs:896-899, 918`).
   - There are no other `account/` notifications
     (`protocol/common.rs:1906-1907, 1958-1961`).
   - `emittedAtMs` sits beside `method` and `params`, not inside `params`
     (`common.rs:1966-1981`).
   - Two auth-related notifications sit outside the namespace:
     `modelProvider/authRecoveryStarted` and `modelProvider/authRecoveryCompleted`
     (`common.rs:1920-1921`). Their params are
     `{threadId, turnId, provider, message}` (`v2/notification.rs:11-16`), and
     the pinned transport test instantiates one for Amazon Bedrock
     (`app-server/src/transport_tests.rs:196-210`). Today the turn-evidence
     allowlist withholds them silently (`codex_protocol.py:546-547`); nothing
     refuses them.
5. **`account/rateLimits/read`.**
   - The request is `{"id": n, "method": "account/rateLimits/read"}` with no
     params (`common.rs:1234-1238`; wire test `:3014-3030`).
   - The response is `{rateLimits, rateLimitsByLimitId, rateLimitResetCredits,
     accountId, rateLimitUpsell}` (`v2/account.rs:314-325`). `accountId` is
     identity, and `rateLimitUpsell` is arbitrary JSON.
   - `rateLimits` carries:
     - `credits {hasCredits: bool, unlimited: bool, balance: string|null}` (`:671-675`);
     - `spendControlReached` (`:573`);
     - `rateLimitReachedType` (`:599-606`);
     - `primary` and `secondary {usedPercent, windowDurationMins, resetsAt}` (`:650-655`);
     - `individualLimit` (`:690-696`);
     - `planType`.
   - **The headline `rateLimits` is not reliably the Codex bucket.** It is the
     snapshot whose `limitId` is `codex` if one exists, and otherwise the
     *first* snapshot returned (`account_processor.rs:1177-1181`).
     `rateLimitsByLimitId` maps a snapshot with no `limitId` to the key `codex`
     too (`:1164-1173`). So only a map entry whose own `limitId` is `"codex"`
     identifies the Codex bucket affirmatively.
   - The handler calls `auth_manager.auth()`, which can refresh the token
     proactively (`account_processor.rs:1134`; `manager.rs:2345-2359`). It then
     makes two concurrent GETs through `BackendClient` to the configured
     `chatgpt_base_url` (`account_processor.rs:1146-1155`): `/wham/usage`, and
     `/wham/rate-limit-reset-credits` with a 5 s timeout, falling back on
     failure (trace).
   - It errors when there is no account, or when the auth is not a Codex
     backend auth (`account_processor.rs:1134-1145`).
   - The pinned source has no auto-reload field anywhere (grep of the tree for
     `reload` and `top_up` variants in account and credit types).
6. **`account/read` versus expiry.** With `refreshToken:false`, `account/read`
   makes no call of its own (`account_processor.rs:1019-1032, 1109-1121`). It
   reports from `auth_cached()`, and reports **no account** only if that
   manager has already recorded a permanent refresh failure
   (`model-provider/src/provider.rs:401-410`). In the sealed configuration, no
   caller of the second manager's `auth()` runs before `account/read`. The
   cloud loader's `auth()` belongs to the other instance (`app-server/src/lib.rs:509-512, 758-761`).
   So an expired or revoked login normally still reads as a ChatGPT `pro`
   account. The readback is the first request that exercises the credential.
7. **Plan literals.** `PlanType` serializes in lower case, with both `pro` and
   `prolite` (`protocol/src/account.rs:9-44`). Which one a "Pro 20x"
   subscription reports is not in source (see open question 1).
8. **Cloud-managed configuration.**
   - The loader is installed at every start (`app-server/src/lib.rs:509-517`,
     trace). It fetches only for business-like, education-like or `Enterprise`
     plans (`cloud-config/src/service.rs:49-57`, read directly). `pro` and
     `prolite` are neither (`protocol/src/account.rs:60-86`).
   - A fetched bundle becomes a precedence-15 layer below the user
     configuration. It can set any key the user configuration leaves unset, and
     its requirements include non-restrictive `hooks` (trace).
   - For the expected plan it is neither fetched nor read from cache (trace).
9. **Auxiliary startup requests are configuration-gated.**
   - Plugin startup tasks run only when `config.plugins_enabled`
     (`core-plugins/src/manager.rs:2815-2858`, read directly). That includes the
     featured-IDs request, which is sent even without authentication.
   - `model_catalog_json` selects a static models manager, and the file must
     contain at least one model (`core/src/config/mod.rs:2052-2061`, read
     directly; `models-manager/src/manager.rs:289-305`).
   - Analytics has `[analytics] enabled` (trace).
   - Remote control needs a persisted enrollment, and a fresh home has none
     (trace).
   - The feature keys `plugins` and `apps` exist
     (`features/src/lib.rs:1244-1249, 1322-1327`), as do `forced_login_method`,
     `cli_auth_credentials_store` and `model_catalog_json`
     (`config/src/config_toml.rs:257, 264, 368`).
10. **Device-code login.** `codex login --device-auth` refuses unless ChatGPT
    login is allowed. It uses only the issuer, `https://auth.openai.com` by
    default (`login/src/server.rs:59`): `/api/accounts/deviceauth/usercode` and
    `/deviceauth/token` (`login/src/device_code_auth.rs:68, 107, 165-172`). It
    prints the URL and one-time code to **stdout**, and success or failure to
    **stderr** (`device_code_auth.rs:158-163`; `cli/src/login.rs:354-362`). It
    also always opens a file log, `codex-login.log`, under `log_dir`
    (`cli/src/login.rs:48-113`, called at `:325`). `log_dir` defaults to `$CODEX_HOME/log`
    (`core/src/config/mod.rs:906-907`). The app-server likewise writes its own
    state under `CODEX_HOME`. So `CODEX_HOME` holds more than the two bound
    files.
11. **Existing relay evidence.**
    - Denials are counted by reason only (`egress.py:588, 610`). A destination
      denial is raised at `egress.py:645-647`.
    - Every accepted socket counts against `EgressPolicy.connections` before it
      is handled (`egress.py:590-596`).
12. **Launcher contract.** `before_spawn` must return a `BindingCheck`
    (`linux.py:469-474`), and the store's lock must be one of the guard
    descriptors (`linux.py:470-471`). `StoreMaintenance` exposes only
    `store_path` and `generation_floor` (`operator_store.py:168-173`).
13. **Existing pins that N4 changes on purpose:**
    - the recorded forward cost, pinned in
      `test_codex_matrix.py:213-233` (`account/rateLimits/updated` refuses a
      turn);
    - the six-method sequence `SIX` (`test_codex_matrix.py:68-71`, used in eight
      places);
    - `test_the_limit_reached_conversation_takes_no_overage_input`
      (`:286-292`), which **stays true** under this design.

## Design

### 1. Narrow layout and sealed configuration

**Amended after review (P1 C3, P1 config/relay).** Both files are bound by
**descriptor**, the way N3a pins the store and lock, and not by a path that is
re-checked. The review found two problems with the first draft:
- It placed the configuration in the relay's directory, which
  `EgressRelay.__aenter__` must create fresh with `mkdir` and no `exist_ok`
  (`egress.py:486-487`). The two could not coexist.
- It handed bubblewrap a path after checking that path with `lstat`. That left
  a window between check and use.

**`linux.py`, `LinuxLauncher.argv`.** When `native_store` is given, the one
`--bind <store> /vendor-store` is replaced by:

```text
--dir /tmp/home/.codex
--ro-bind-data <config fd> /tmp/home/.codex/config.toml
--bind-fd <credential fd> /tmp/home/.codex/auth.json
--setenv CODEX_HOME /tmp/home/.codex
```

- `NativeStoreMount` gains two descriptor fields, `configuration_fd` and
  `credential_fd`, and no path. It still carries no mount catalogue: both zone
  paths are constants in `linux.py`.
- **Descriptor passing is new plumbing.** The launcher adds both descriptors to
  the supervisor's `pass_fds` (`linux.py:617`). The supervisor currently starts
  bubblewrap with `close_fds=True` and passes no descriptors
  (`_supervisor.py:137`). It gains one argument, `--mount-fds=a,b`, and passes
  exactly those descriptors to bubblewrap, which consumes them. The supervisor
  lives in the immutable runtime, so the runtime digest changes.
- **Before implementation:** confirm that the pinned bubblewrap
  `0.9.0-1ubuntu0.3` provides `--bind-fd` and `--ro-bind-data`, from that
  package's own manual. If either is absent, **stop for review**. Falling back
  to path binding is not an option.
- The egress leaf and the bridge prefix are unchanged.
- `CODEX_HOME` is set explicitly even though it equals the default. That keeps
  routing independent of `HOME`.

**`operator_store.py`.**
- `CREDENTIAL_FILE = "auth.json"`.
- `open_credential(opened: OpenedBundle) -> int`:
  - `openat(store_fd, "auth.json", O_PATH | O_NOFOLLOW | O_CLOEXEC)`, relative
    to the store descriptor that N3a already identity-checks, never to a path;
  - `fstat` of that descriptor must show a regular file, `st_nlink == 1`,
    `st_uid == os.getuid()` and mode exactly `0600`;
  - it returns the descriptor. `O_PATH` cannot read, so no content is read or
    hashed (ADR 0021:171-174).

  Absence or any other shape raises `ContractViolation("the operator store has
  no qualified credential file")`. The descriptor that bubblewrap binds is the
  object that was checked.
- `HeldStoreLock` and `StoreMaintenance` both expose this through their opened
  bundle. `check_held` and `StoreMaintenance.check()` already re-prove the
  store object with `_require_same_objects`.
- Both constants live in this module, so `BINDING_LAYOUT_LAW`, which digests
  the module source (`operator_store.py:1265-1266`), now covers the layout.
  Every existing descriptor refuses until it is republished. That was already
  the rule for any `operator_store.py` edit.

**`codex.py`, the handle.**
- The provider retains its `configuration` string.
- In `_converse`, before launch, the configuration goes into a `memfd`:
  1. `memfd_create("codex-config", MFD_CLOEXEC | MFD_ALLOW_SEALING)`;
  2. write the bytes;
  3. seal it with `F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL`;
  4. re-read it from offset 0 and compare its digest with
     `identity.configuration_digest`.

  Once sealed, the content cannot change. There is no file on disk, nothing
  collides with the relay's directory, and nothing needs disposal: the
  descriptor closes in the handle's `finally`, after `exchange` returns.
- `before_spawn` opens the credential descriptor from the **held** bundle
  (`open_credential(held._opened)`, after `check_held`), synchronously and
  immediately before spawn. It closes that descriptor in the same `finally`.
- The lane does the same with its maintenance or active custody.

**Why a single-file bind.**
- `rename` and `unlink` over a bind mount fail with `EBUSY`. A zone can
  therefore never replace, delete or symlink the credential. It also cannot
  reach any other store content, which it can today through `/vendor-store`.
- The zone's `CODEX_HOME` holds more than these two binds (review P2). The
  pinned client also writes `log/codex-login.log`, and the app-server's own
  state and logs, under `CODEX_HOME` (Inputs 10). Every one of those paths is
  in the zone's own tmpfs. They are destroyed with the namespace, never
  host-visible and never read by the lane. The exact inventory is: two
  host-originated files (the configuration read-only, the credential
  read/write), and everything else disposable.
- The pinned client's in-place save (Inputs 3) is exactly what a file bind
  supports.
- A symlink from `CODEX_HOME` into a directory mount was rejected: pre-login
  logout deletes the symlink, so the new login is saved to tmpfs and lost
  (Inputs 3).

**What the sealed configuration must say.** It is operator input, fixed by
digest, and not code. The provider already refuses one whose top-level `model`
is outside the profile inventory (`codex.py:1851-1855`). N4's configuration:

```toml
model = "<the pinned catalog's default model>"
model_catalog_json = "<runtime path of the fixed catalog, see Host-runtime interface>"
cli_auth_credentials_store = "file"
forced_login_method = "chatgpt"
check_for_update_on_startup = false
web_search = "disabled"
[analytics]
enabled = false
[features]
plugins = false
apps = false
shell_tool = false
unified_exec = false
apply_patch_freeform = false
view_image = false
multi_agent = false
code_mode = false
js_repl = false
```

- There is no `[model_providers]` table. The built-in `openai` provider is what
  makes `requiresOpenaiAuth` true, which is gate fault 3's positive case.
- `forced_login_method` is defence in depth. The mode gate does not rely on it.
- The feature list is the fixture's (`tests/native_startup.py:70-78`) plus
  `plugins = false`.

**The auxiliary-network census** (orchestrator decision, from the census in
`M8-N4-proxy-bridge.md`). Remove auxiliary traffic at its source, and keep the
relay's denial as defence in depth. Each default-on feature that starts
network traffic not needed for authenticated startup or a turn is disabled by
its exact key. The keys are part of the configuration bytes, so they are part
of `configuration_digest`.

| Origin | Key, default | Pinned gate |
| --- | --- | --- |
| Plugin startup: curated sync, including the backup-archive fallback that produced the unsolicited CONNECT; remote catalog; installed; suggested; featured IDs | `[features] plugins = false` (default true) | `features/src/lib.rs:1322-1327`; `core-plugins/src/manager.rs:688-709, 2815-2858` |
| Apps and connectors | `[features] apps = false` (default true) | `features/src/lib.rs:1244-1249`. No startup trigger was found (trace, unverified), so it is disabled on principle |
| Remote models list, every 4.5 minutes | `model_catalog_json = <runtime path>` | `config/src/config_toml.rs:368`; `core/src/config/mod.rs:2052-2061` |
| Analytics events | `[analytics] enabled = false` (enabled unless false) | `config/src/types.rs:221-224` |
| Update check | `check_for_update_on_startup = false` | App-server reports only (census) |
| Web search | `web_search = "disabled"` | A turn-time tool; N5 |

What sealed configuration **cannot** disable is listed, not tolerated:
- The cloud-config loader (not fetched for `pro`, Inputs 8).
- The remote-control enrollment lookup. It makes no network call from a fresh
  home (trace).

Neither sends a CONNECT for the expected plan. Any CONNECT they did send would
be denied as `destination` unless it is sealed, and a clean startup must show
zero denials.

### 2. The startup phase and the readback

**`codex_protocol.py`** gains:

- `rate_limits_read_request(id) -> {"id": id, "method": "account/rateLimits/read"}`.
- `spend_reading(reply, expected) -> SpendReading | None`. This is a frozen
  dataclass holding only:
  - `plan` (the wire value, compared and never published);
  - `has_credits`, `unlimited` and `spend_control_reached` (`bool | None`);
  - `balance_zero` (`bool | None`). It is `True` only for a string of at most
    32 characters that parses as a finite decimal equal to zero.
  - `rate_limit_reached` (`bool | None`: whether `rateLimitReachedType` is
    non-null);
  - `primary_used_percent` and `secondary_used_percent` (`int | None`, bounded
    by `_number`).

  **Amended (P1 C4).** It reads exactly one bucket:
  `result.rateLimitsByLimitId["codex"]`, and only if that entry's own
  `limitId` is the string `"codex"`. The vendor maps a snapshot with no id to
  the same key (Inputs 5).
  - The headline `rateLimits` is never judged, because it may be the first
    unrelated bucket.
  - If the map or that entry is absent, or the entry's `limitId` is not
    `"codex"`, the reading is `None` and refuses: **stop**. There is no
    fallback to the headline.
  - `accountId`, `rateLimitUpsell`, `rateLimitResetCredits`, other buckets,
    `limitName` and `individualLimit` are never read.
  - An error reply or a missing result also returns `None`.
- `spend_faults(reading, expected) -> tuple[str, ...]`, the pre-turn bound:
  - `None` refuses ("the rate-limit readback is an error or carries no result");
  - `plan` is compared to `expected.plan_type` only when present;
  - the credits rule is `has_credits is False and unlimited is False and
    balance_zero is not False`. An absent `credits` object refuses: absence is
    unknown, never zero.

  Fault text names only literal field names and `named_value` of the plan.
- `spend_change_faults(before, after)`. It compares `has_credits`,
  `unlimited`, `balance_zero`, `spend_control_reached` and
  `rate_limit_reached`, in the style of `account_change_faults`. Used-percent
  changes are expected and are not compared.
- `rate_limit_of(before, after) -> RateLimitInfo`:
  - `is_using_overage=None` always (I4: the pin has no such fact);
  - `detail` holds `before.*` and `after.*` for the seven fields, keeping only
    those that are present.

  This replaces the projection from `turn.rateLimits` (`codex_protocol.py:914-942,
  1030`). The pinned `Turn` has no such field (#78 research,
  `v2/thread_data.rs:366`), so that code is dead against the pin.

**The bound is code, not input.** This is the owner's current N5 bound: no
purchased credits, with the readback taken before and after. It lives in
`PROTOCOL_REVISION`. A different owner bound is a new revision, never a
parameter, so `test_the_limit_reached_conversation_takes_no_overage_input`
stays true. It applies to every profile the adapter can make available. A
`forbidden` profile is already forced unavailable (`codex.py:1868-1869`).
Automatic reload is not observable in the pinned client (Inputs 5). The
"reload off" half of the N5 bound therefore stays operator-attested and is
re-captured before N5, which [Limits](#limits-carried) records.

**`codex.py`, `CodexConversation._converse`**, in the new order:

```text
initialize, initialized
account/read            -> account_faults                  (unchanged)
account/rateLimits/read -> spend_faults                    refuses before thread/start
  [startup_only: gate_completed = True; return]
thread/start, turn/start, collect                          (unchanged)
account/read            -> account_faults + account_change_faults
account/rateLimits/read -> spend_faults(after) + spend_change_faults(before, after)
gate_completed = True
```

- A pre-turn readback fault returns before `thread/start`: no thread, no tools
  offered, no turn. A pre-acceptance readback fault discards the turn, exactly
  as an account fault does.
- **`startup_only: bool = False`** is a constructor keyword and the only new
  branch. `gate_completed` now means "the last gate of this conversation's
  phase ran to its end". For startup that last gate is the first readback, and
  the existing `finally` (`codex.py:375-394`) turns any abort into
  `GATE_INCOMPLETE_FAULT` in both modes.
- The conversation keeps `before_spend` and `after_spend` as attributes, next
  to `withheld_methods`, for the lane's evidence.
- The handle passes `rate_limit_of(before, after)` into the outcome through the
  observation. `decode_turn` is unchanged apart from where it takes that field.
- `CodexOperatorHandle` never sets `startup_only`. P7 pins this.

**Why the readback belongs in the task conversation, not only in N4.** It is
the only spend source N5 has (#78 research). It is also the first pre-turn
request that uses the credential (Inputs 6). Without it, an expired or revoked
login clears the gate and fails only after `thread/start`.

### 3. Account notifications: the allowlist

Inputs 4 enumerates the notifications this repository has so far treated as
unknown (`codex_protocol.py:536-544`). The decision:

| Method (pinned) | Mode or identity field | Decision |
| --- | --- | --- |
| `account/updated` | `authMode`, `planType` | **Refuse**, always. It is the mode-change signal |
| `account/login/completed` | login flow (`loginId`, `success`) | **Refuse**, always. This conversation never starts a login |
| `account/rateLimits/updated` | `rateLimits.planType` | **Admit** only if `params` is an object whose keys are exactly `{"rateLimits"}`, `rateLimits` is an object, and its `planType` is absent, null or `expected.plan_type`. Otherwise refuse |
| any other `account/…` | unknown | **Refuse** (the namespace default is unchanged) |
| `modelProvider/authRecoveryStarted`, `…Completed`, any other `modelProvider/…` | `provider`, `message` | **Refuse** (amended, see below) |

**Implementation.**
- `is_account_record` becomes `account_notice_faults(record, expected) ->
  tuple[str, ...]`. `_absorb` (`codex.py:501-503`) and the callback path
  (`codex.py:911`) both route through it.
- An admitted notice is neither transcribed nor treated as damage. It is
  counted as withheld, like any record outside the turn-evidence allowlist, so
  the transcript marker still reports it.
- Its spend fields are not judged mid-turn. The post-turn readback judges the
  same state affirmatively.

**Why `planType` and not only the method.**
- The snapshot is documented as sparse: "Nullable account metadata … does not
  clear a previously observed value" (`v2/account.rs:553-557`). So absence is
  admissible.
- A present, different plan is a vendor-reported plan change inside the window
  that the two readings bracket but cannot cover, exactly what
  `ACCOUNT_NOTICE_FAULT`'s docstring describes.

**Outside the namespace (amended, P1 C6).** Every `modelProvider/` method
**refuses**. That includes the two pinned auth-recovery notifications (Inputs
4), with the same neutral fault that names the method.
- The first draft withheld them on the grounds that recovery is only a
  permitted refresh. The pinned payload names a provider, and the pinned test
  instantiates it for Amazon Bedrock. So an auth-recovery event is a
  provider-authentication event, and ADR 0021:228-240 requires it to be
  refused, not discarded.
- The post-turn readings cannot undo anything that happened during the turn.
- A provider or auth-recovery event ends the phase as a refusal.

The cost is recorded as the next forward cost: a legitimate refresh after a
401 during an N5 turn discards that turn.

### 4. Per-destination relay evidence (`egress.py`)

In `EgressRelay`, and nowhere else:

**Amended (P2 C9 ×2).** Only sealed destinations are ever named.

- `_handle`: next to `accepted`, record
  `observed[f"accepted:{d.host}:{d.port}"]`, where `d` is the matched
  `EgressDestination` from the sealed policy. This needs `_open` to return it
  alongside the socket.
- `_pump`, upstream to client: on the first non-empty chunk only, record
  `observed[f"relayed:{d.host}:{d.port}"] += 1`. The name was changed from
  `answered` after review. It means exactly this: the pinned address returned
  at least one byte that was relayed. It is **not** a TLS validation result and
  **not** proof that the address serves the vendor endpoint, because any TCP
  service would satisfy it. Only the client's own TLS validation, and the
  readback succeeding through it, say that. An accepted connection that
  relayed nothing is a stale-address *signal*, and nothing more.
- **Denials stay counted by reason only** (`denied:destination` and the other
  reasons), as today. The first draft keyed denials by the attempted
  hostname. The review showed that this lets a compromised credential-bearing
  client push up to 253 chosen bytes into retained evidence. Now only names
  drawn from the sealed policy appear, and the operator chose those.
- Keys are bounded by the policy's own destination count.
- This changes `enforcement_build_digest`, because it digests the module
  source (`egress.py:180-182`). The N4 egress identity is new in any case.

The test suites that need a refused hostname, such as L2's control, capture
CONNECT heads in test code, exactly as the bridge CI proof did. The relay does
not.

### 5. Launches held under maintenance

The operator's login and the qualification startup must both run in the real
zone behind the relay (authorization: "through the N3b relay"), and while the
maintenance lock is held (ADR 0021:186-189). The launcher already requires both
of the pieces below (Inputs 12). Maintenance just doesn't expose them.

**`operator_store.py`.** `StoreMaintenance` gains two things:
- `lock_fd`, which is the maintenance context's own open description;
- `check() -> BindingCheck`, which does the following:
  - refuses once `closed`;
  - reopens the bundle;
  - requires `active.json` to still be this key's withdrawal record, with this
    floor;
  - requires `_require_same_objects` against the context's opened bundle;
  - returns `BindingCheck(digest("native-operator-maintenance", 1, {"key": key,
    "generation_floor": floor}))`.

That digest is a positive in-memory check of the maintenance selection. It can
never equal a provider's binding digest, because the domain differs.

**Qualification runs inside the same maintenance context, straight after the
login**, and before the next generation is published. There is no
`qualify_offline` helper.
- **What the floor proves.** Every descriptor is published after the
  withdrawal: publication takes the lock, and the floor is the highest
  descriptor at maintenance time. A later maintenance, and therefore any
  re-login, raises the floor to at least g, which makes g impossible to
  activate (N3c S-tests). A qualification run in *this* maintenance is
  therefore invalidated mechanically by any later one.
- **What it does not prove (amended, P1 C7).** It does not prove that a
  completed qualification preceded the activation. `activate_offline` accepts
  opaque, caller-supplied conformance revisions and says so
  (`operator_store.py:1176-1184`). That remains N3c decision 3's accepted
  limit: qualification is operator-asserted. The first draft's claim that
  "ADR 0021:195-197 is met" is withdrawn.
- **Cheap strengthening.** The lane prints
  `digest("codex-authenticated-startup-evidence", 1, <evidence file bytes>)`.
  The operator passes that value as the production launch identity's two
  conformance revisions, so the sealed identity names the exact evidence it
  rests on. `activate_offline` still neither records nor checks it. Making
  activation *verify* it would need a durable field in `active.json`, which
  this design does not add (open question 5).
- **The residual.** A same-uid host process could edit the store between the
  two. That is the existing trusted-custody limit (N3c).

**Lane module: `substrate/executors/codex_lane.py`.** It is new, and it
composes existing parts only.

- `async run_login(maintenance, launcher, policy, *, binary, configuration,
  deadline, out) -> LaneEvidence`. It:
  - runs `codex login --device-auth` through `LinuxLauncher.exchange`;
  - passes a `NativeStoreMount(lock_fd=maintenance.lock_fd,
    configuration_fd=<sealed memfd>, credential_fd=<opened in before_spawn>,
    before_spawn=…)`, where `before_spawn` runs `maintenance.check()` and then
    `open_credential(...)`;
  - uses `guard_fds=(maintenance.lock_fd,)`;
  - wraps the launch in `EgressRelay(policy, lane_dir / "relay", deadline,
    check)`. The relay creates that directory itself.

  Its conversation copies stdout chunks to `out`, the operator's terminal, and
  keeps nothing. Stdout carries the one-time code (Inputs 10), so it never
  reaches the evidence. Stderr stays inside the launcher's bounded head and
  tail, and the evidence records only its byte count.
- `async run_startup(custody, launcher, policy, *, expected, configuration,
  deadline) -> LaneEvidence`. It uses the same composition with
  `CodexConversation(startup_only=True, …)`. `custody` is either the
  maintenance context (qualification) or a `HeldStoreLock` from
  `BindingStore` (the active path, runbook S8). Both supply a store path, a
  lock descriptor and a `BindingCheck`.
- `LaneEvidence` is a closed, bounded record (listed below). It is written to
  its file only by `write_evidence`, which sets `completed: true` as the last
  field and writes with create-exclusive. A missing or incomplete file is a
  failed run.
- `main(argv)` is a thin argument parser for the host operator. It does no
  interactive prompting of its own. It has two subcommands:
  - `login`;
  - `startup --custody {maintenance,active} --expected PLAN [--hold SECONDS]`.
    `--hold` pauses after the readback is judged and before stdin closes. It
    is bounded by the lane deadline, and it exists only for control S6a.

`lane_dir` is a fresh `0700` directory under an operator-given root.
- It holds only the relay's own directory, which the relay creates and removes
  (`egress.py:479-556`). The configuration is a memfd, not a file.
- It is removed at exit, after the relay has exited.
- Its path length is checked with the provider's existing rule
  (`codex.py:1843-1849`).

**Stop rules in the lane, mechanically.**
- **Any** relay denial of any reason in a lane run expected to be clean adds
  the fault "the relay denied a connection". That is the orchestrator's
  decision: zero denials is an affirmative "no auxiliary traffic" fact. It is
  paired with L2's same-run positive control, which shows that the counter
  counts. Only the S6b control expects a denial, and it declares that in
  advance.
- Any conversation fault, any launcher failure, or a missing credential file
  after login is a fault.
- The lane never retries. The operator procedure stops on any fault.

**Evidence (closed schema).**

```text
schema_version, lane ("login" | "startup"), custody ("maintenance" | "active"),
commit, executable_digest, runtime_digest, configuration_digest, egress digests (5),
generation_floor | binding_digest,
methods_sent[], withheld_methods[<=16], faults[] (bounded),
gate {account_type_ok, plan_ok, requires_openai_auth},
readback {before.*} (startup) — the seven SpendReading fields, plan as plan_ok only,
relay {accepted:{sealed h:p: n}, relayed:{sealed h:p: n}, denied:{reason: n}},
credential {present, regular_0600, mtime_changed},
process {returncode, payload_returncode, timed_out, elapsed_s, stderr_bytes},
completed
```

It never holds stdout, stderr text, an email, account ID, token, device code,
file content, content hash, or a hostname outside the sealed policy.
- `mtime_changed` compares the `fstat` of the credential descriptor before and
  after the run. That is metadata only.
- **Plan literals (amended, P2 contradiction).** A plan string appears in
  evidence only where the adapter's public fault text already names it: a
  short literal from the closed alphabet `named_value` admits
  (`codex_protocol.py:634-658`), such as `'prolite'`. The schema carries no
  other plan string, and `readback` carries `plan_ok` only. The runbook's
  retention line says the same.

### 6. Destination inventory and pinning

| Lane | Destinations sealed | Why (pinned) |
| --- | --- | --- |
| login | `auth.openai.com:443` | Device-code endpoints under the issuer (Inputs 10). Token exchange and pre-login revoke use the same host (`manager.rs:197-198`) |
| startup | `chatgpt.com:443`, `auth.openai.com:443` | The readback's two GETs go to `chatgpt_base_url`, which defaults to `https://chatgpt.com/backend-api/` (Inputs 5). A proactive refresh goes to `auth.openai.com/oauth/token` |

Nothing else is sealed. With the configuration of section 1, the remote models
list, plugin tasks, analytics and the cloud bundle are all excluded (Inputs
8-9).

**The shared host.** `chatgpt.com` also carries model traffic
(`/backend-api/codex/...`). As ADR 0021:262-265 anticipates, the relay cannot
separate phases. The phase fact is the protocol order: the startup lane sends
four recorded methods and never `thread/start`, pinned by P7. It is not an
egress fact.

**Pinning and CDN practicality.** The relay dials one literal address per
`(host, port)` and never resolves (`egress.py:121-145`).

1. **Resolve.** At each session's step S1, the operator resolves each host
   once, on the host and outside any zone, with the host's configured resolver.
   The record is: host, the address chosen (the first global IPv4 answer),
   resolver, and UTC time.
2. **Seal.** The policy is built from that record, which fixes
   `resolver_policy_digest`.
3. **What fails closed.**
   - A stale or unreachable address shows up as `denied:upstream_unreachable`,
     or as accepted but never `relayed`.
   - The client's request then fails, and the conversation refuses (a readback
     error, or no reply).
   - The operator never re-resolves inside a run. Re-pinning is a new egress
     identity and therefore requalification.
4. **What N4 measures.** Whether one pin still served the login, the
   qualification and the restart run hours later. The positive fact is the
   *client's* request succeeding through that pin: the login's exit 0, or a
   readback judged. That fact covers the vendor endpoint because the client
   validated TLS itself. `relayed` above zero only corroborates it, and the
   address must be unchanged between records. This is the "CDN address
   practicality" finding. N4 neither claims nor needs address stability during
   a model turn (see Limits).

### 7. The unsolicited `CONNECT chatgpt.com:443`: traced, and removed at the source

**The trace.** A separate researcher traced it, and the orchestrator verified
the feature key. It is the curated-plugins startup sync's backup-archive
fallback (`core-plugins/src/manager.rs:26-27`
`CURATED_PLUGINS_BACKUP_ARCHIVE_API_URL`, reached through `:340-364`).
- It is spawned when `MessageProcessor` is constructed, before stdin is read
  (`app-server/src/lib.rs:452, 907`; `message_processor.rs:525-543`).
- It runs whenever plugins are enabled and no Codex-backend authentication is
  active (`manager.rs:688-709`).
- It tries `git`, then `api.github.com`, then `chatgpt.com`. It carries no
  credentials, only the default headers (`startup_sync.rs:971-989,
  1022-1029`). That fits the missing `user-agent` line.
- Neither startup nor turns need it; its failures are only logged.
- It is disabled by `[features] plugins = false`
  (`features/src/lib.rs:1322-1327`, consumed at
  `core/src/config/mod.rs:1645`).

**Decision (orchestrator):** outcome A, "remove at the source, keep the relay
denial as defence in depth", applied to the whole census (section 1). The
first draft had an `expected_refused` mechanism (outcome B). That mechanism is
withdrawn: no denial is tolerated.

This matters because N4 seals `chatgpt.com:443` for the readback. With a login
active, the curated sync itself would not run (Codex-backend authentication
disables it). The *other* plugin tasks would, and the relay could not refuse
them. The source gate is therefore what removes them. The proof:

- **L2, credential-free, with a same-run positive control.**
  - The pinned binary with the **production** configuration and no login
    produces **zero** relay denials and zero accepted connections. With no
    login, the readback is never reached, because the gate refuses first.
  - The same step with the fixture's configuration (plugins on) produces
    `denied:destination` of at least 1. The test's own head capture names
    `chatgpt.com:443`. That shows the zero is a measurement, not a blind
    counter.
- **Every operator lane expected to be clean** must show zero denials, or it
  stops (section 5).
- **Limit.** With a login, an accepted `chatgpt.com` connection cannot be
  attributed to a single request, because HTTP/2 multiplexes. So authenticated
  absence of auxiliary requests rests on the source gates and L2's control,
  not on connection counts.

### 8. Authority-input inventory (pinned client, startup phase)

| Input | Disposition | Proof |
| --- | --- | --- |
| `config.toml` in `CODEX_HOME` | **Fixed and revision-bound**: the sealed bytes, as a sealed memfd bound read-only by descriptor, their digest checked against the launch identity before spawn | L1 (read-only), P8 |
| Other `CODEX_HOME` content (`log/codex-login.log`, the app-server's state and logs) | **Disposable**: zone tmpfs only, destroyed with the namespace, never host-visible and never read by the lane | L1 (inventory of host-visible paths) |
| `auth.json` | **Vendor-owned.** Its mode is **enforced before use** by the gate and readback, and its refresh stays inside the one bound file | L1, P6, S4 |
| Cloud config bundle (enterprise layer) | **Excluded for the expected plan** by the vendor's eligibility rule. A plan change is refused by the gate before any thread exists | Inputs 8 (source). Limit: layer application comes before the gate for an eligible plan |
| `/etc/codex` system configuration and requirements | **Excluded**: absent from the immutable runtime | Existing bootstrap evidence (`_native_startup_bootstrap.py:36-39`). The installer interface requires it absent |
| Project `.codex` | **Excluded**: the working directory `/tmp` is a fresh tmpfs | argv (`linux.py:346`) |
| Environment | **Fixed**: `--clearenv` plus `HOME`, `PATH`, `LANG`, `CODEX_HOME` and the bridge's `HTTPS_PROXY` | argv test |
| Remote models list | **Excluded** by `model_catalog_json`, whose catalog is fixed in the runtime digest | Inputs 9, L2 |
| Plugins and featured warm-up | **Excluded** by `plugins = false` | Inputs 9, L2 |
| Analytics and OTel | **Excluded** by `[analytics] enabled = false`. The app-server default already leaves OTel off (trace) | L2 |
| Remote control | **Excluded**: a fresh home has no enrollment (trace) | L2 (zero heads) |
| Mid-turn plan change | **Enforced**: `account/rateLimits/updated` `planType`, the pre-acceptance reading, and the post-turn readback | P5, P6 |
| Provider authentication recovery (`modelProvider/…`) | **Enforced**: refused on sight | P5 |

Tools and callbacks do not exist before `thread/start`. N2 and N3 own their
identity-independent confinement, and N4 does not re-prove it.

### What does not change, and which identities are re-derived

**No contract changes.** Nothing changes in:
- the grant predicate, the profile and the identity *record shapes* (no L0
  edit);
- the lease and journal;
- the walker;
- the WRITE callback mediation;
- the relay's policy, rules and deadline;
- the bridge;
- the provider's availability law. `vendor_conformance_qualified` stays false,
  and default production unavailability stays.
- the adapter's fixed `clientInfo`.

**Identity values move (amended, P2).** Every value below is source-derived,
so each moves:

| Changed source | Values that move | Consequence |
| --- | --- | --- |
| `linux.py` (layout, descriptor mounts) | `LinuxLauncher.revision`, and so `isolation_revision` (`linux.py:305-315`) | Every published launch identity must be re-derived. The provider refuses a stale one (`codex.py:1793-1807`) |
| `_supervisor.py` (`--mount-fds`), and the runtime catalog file | `runtime_digest` | Same. The installer builds the new runtime |
| `codex_protocol.py` | `PROTOCOL_REVISION`, which is both `decoder_revision` and `callback_protocol_revision` (`codex.py:195, 257-265`) | Same. The N2 and N2 WRITE mutation anchors are refreshed |
| `codex.py` | `ADAPTER_REVISION` | Same |
| `operator_store.py` | `BINDING_LAYOUT_LAW` and `BINDING_MOUNT_LOCK_LAW` | Every descriptor refuses until republished, and the CI fixtures republish |
| `egress.py` | `enforcement_build_digest` | New egress identity |
| Sealed configuration | `configuration_digest` | New launch identity |

No conformance record from N2, N3 or the bridge carries over to the new
values. The CI lanes re-run them at the N4 head, and no earlier head's
evidence is claimed for it.

## Positive controls kept from rev 2 N4

These are rev 2 lines 234-248, with the principal/scope comparison replaced as
rev 3 directs.

| Rev 2 control | N4 form | Where |
| --- | --- | --- |
| Absent account refuses before any turn | Pinned binary with no login: `NO_ACCOUNT_FAULT` only, `requiresOpenaiAuth` true, no readback, no `thread/start` | L2 (CI) |
| Mismatched account refuses | Replaced by **mode and plan refusal**. The operator runs the startup lane once with `ExpectedAccount("plus")`. The gate refuses and names the observed literal. No vendor change, and only the permitted methods | S6c |
| Startup failure tears down without a turn | The startup policy omits `chatgpt.com`. The readback fails, so the run refuses before `thread/start` | S6b |
| Refresh | `accepted:auth.openai.com:443` above zero **and** `mtime_changed` on a later run. Otherwise the row reads "unmeasured" | S10 |
| Expired login | A readback error refuses before the turn, even though `account/read` alone would pass (Inputs 6). Portable: P6 with a scripted error reply. Live: whatever S10 observes | P6, S10 |
| Quiescent maintenance | While a startup lane holds the lock, `maintain_offline(wait_s=0)` refuses | S6a |
| Concurrent acquisitions | The same lock (N3a, Linux-proved) | Inherited |
| Authenticated startup egress | Per-destination relay record on every lane | S3, S4, S8, S9 |
| Teardown and restart | Reboot, then maintain (re-anchor), qualify, publish, activate. The old generation refuses | S9 |
| Full principal/scope comparison | **Not claimed.** `operator_bound_vendor_identity_unverified` is published, and the evidence records `vendor_identity: "unverified"` | Evidence schema |

## Lifecycle walk

What can already exist when each await resumes, and how a crash at each point
is handled.

**`CodexConversation`, new awaits.**
1. `await _request(rate_limits_read)`, pre-turn.
   - **On resume:** any notification may have been queued: the two pre-turn
     notifications already observed in N2, `account/rateLimits/updated` (now
     admitted under the plan rule), or an `account/updated`, which refuses. A
     forged early reply is caught by the existing order and duplicate rules
     (`_drain_before`, `_once`). The reply carries `accountId` and is
     id-bearing, so it is consumed there and never reaches the transcript.
   - **A refresh inside this request** rewrites `auth.json` in place through
     the bind. Nothing of ours touches the file. The terminal binding check
     compares the store root, not its content (N3 proved this).
   - **A refresh racing the readback, or the terminal check (review P2).** The
     two vendor `AuthManager`s have independent refresh locks, and `save` does
     not lock the file (`storage.rs:206-222`). So a refresh can interleave with
     the readback, and two saves can interleave with each other. The readback
     is judged on its own reply, whichever credentials the vendor used for it.
     The terminal check proves store selection, not credential content or
     freshness. An interleaved save that damages `auth.json` shows up on a
     **later** run, as no account or a failed readback. It is never detected in
     the current one. That is recorded as a limit, and no claim beyond it is
     made.
   - **An abort** (`RecursionError`, cancellation or deadline) leaves
     `gate_completed` false, so the `finally` records `GATE_INCOMPLETE_FAULT`.
     In startup mode, a result is published only by a completed readback.
2. `await _request(rate_limits_read)`, post-turn.
   - **On resume:** the same queue rules apply. A reply that never arrives is a
     refusal, not a wait: the child may have exited. This mirrors
     `codex.py:1147-1151`.
   - **A spend change seen here** discards the result. The turn happened, and
     `produced_output` says so once.

**`run_login`, inside `maintain_offline`.**

| Point | State on resume or at a crash | Outcome |
| --- | --- | --- |
| Context entered | The withdrawal is durable and the lock is held | Every provider refuses (N3c) |
| `lane_dir` created (`0700`, fresh) | Empty | A pre-existing directory refuses. On a crash, a leftover empty directory is removed by the operator. It holds nothing secret |
| Configuration memfd created, written, sealed, re-read and digest-compared (synchronous) | Sealed descriptor, owned by the lane task | A digest mismatch refuses before any relay or spawn. The descriptor is closed in the lane's `finally`, and process death closes it too |
| `EgressRelay.__aenter__` on `lane_dir/relay` | The relay created its own directory and socket (`egress.py:479-501`) | A failed allocation removes the relay's directory (`egress.py:490-497`). Controller death takes the relay with it, and the zone never starts |
| `launcher.exchange`, then `before_spawn` | `maintenance.check()` positive, then the credential `O_PATH` descriptor opened relative to the checked store descriptor and `fstat`-checked. Synchronous, immediately before spawn | A missing placeholder, or a replaced `active.json`, refuses with no spawn. The credential descriptor is closed in the same `finally` as the memfd, after `exchange` returns |
| Conversation reads stdout | The code has been shown to the operator, who signs in on their own device | Controller death: the supervisor keeps the lock until the zone is reaped (N3a owner-death). The vendor may have truncated `auth.json`. The binding stays withdrawn |
| Login exits | `auth.json` has been rewritten in place | The lane records the exit status, relay record and credential metadata |
| Relay exit, then `lane_dir` removal | The relay removed its own directory. A clean exit sets `closed` last (`egress.py:503-556`) | A relay exit error is a lane fault. A leftover `lane_dir` is removed by the operator |
| `write_evidence` | Create-exclusive temporary, `completed` last, `fsync`, then rename | A failure leaves no `completed` file, and the run counts as failed. A leftover temporary is inert and never read |
| Context exits | The lock is released once the supervisor's copy is reaped | No activation can happen: nothing is published yet |

**`run_startup`, inside the same context (qualification).**
- It has the same points as login, with the conversation in startup mode.
- A crash leaves the binding withdrawn with nothing published, and the operator
  repeats maintenance.
- Evidence is written only on completion.

**Publication, then activation.** These are N3c's helpers, unchanged. Between
qualification and activation:
- only vendor processes launched under a lock could touch the store, and none
  runs while the binding is withdrawn apart from these lanes;
- a new maintenance raises the floor, which refuses the activation.

**`run_startup` on the active path (S8).** It uses `BindingStore.open_candidate`,
then `acquire_lock`, then `check_held`, exactly as the handle does
(`codex.py:1335-1344`), and has the same N3a crash semantics.

## Crash and restart matrix

| Crash at | Durable state | Recovery |
| --- | --- | --- |
| Before the maintenance withdrawal | Unchanged | Rerun |
| After withdrawal, before the login launch | Withdrawn | Rerun maintenance and login |
| During login (vendor mid-save) | Withdrawn. `auth.json` may be empty or partial | The next startup lane refuses: no account, or a failed readback. Maintenance and login again |
| During qualification | Withdrawn, nothing published | Maintenance again. The same login stays in the store |
| After qualification, before publication | Withdrawn, evidence complete | Publish, then activate. A lost evidence file means qualifying again |
| After publication, before activation | Withdrawn, g published | Activate with the qualified identity. After another maintenance, g can never be activated |
| During the activation replace | N3c U4/R2 semantics | Read with strict readers, per N3c |
| Host reboot, any state | The anchor names the old boot, so everything refuses (N3c decision 7) | Maintenance re-anchors. Then qualify (no login), publish g+1, activate |

## Negative inferences made affirmative

| Inferred from absence (rejected) | Positive fact recorded |
| --- | --- |
| "No auxiliary traffic" from nothing observed | Zero denials of every reason, and accepted connections only to sealed destinations, **with** L2's same-run control, in which the plugin-on configuration produces a counted denial |
| "Login worked" from exit 0 | Exit 0, **and** the credential file is regular `0600` with `mtime_changed`, **and** the following qualification gate accepts plan `pro` |
| "No model request" from no model traffic | `methods_sent` equals exactly the four methods, `startup_only` is set, and `gate_completed` is latched after the readback. An egress record cannot separate phases on a shared host, and this is not claimed |
| "Within the spend bound" from no credits field | An absent `credits` object refuses. `balance_zero` is `True` only after a parse succeeds |
| "The readback ran" from no readback fault | `gate_completed` is set only after `spend_faults` returns, and the evidence stores the reading's fields |
| "The credential file is the store's" from a bind that did not error | An `O_PATH` descriptor opened relative to the identity-checked store descriptor, `fstat`-checked (regular, nlink 1, uid, `0600`), and the **same** descriptor bound |
| "Refresh works" from no refresh failure | This run made a connection to `auth.openai.com`, the credential file's `mtime` changed during the run, and the run's readback was judged clean. It is **not** proved which vendor manager refreshed, or that the readback used the refreshed credentials (review P2). Without all three facts, the row is **unmeasured** and the profile stays unqualified (criterion 5) |
| "The run completed" from an evidence file existing | `completed: true` is the last field, written with create-exclusive |
| "The notification is benign" from "not `account/updated`" | Exact method, exact params keys, and plan equality |

## Test plan

Both directions from the first commit: every refusal test has an accepting
twin that asserts what is published.

**Portable (scripted peer, every platform).**
- **P1.** The readback request bytes exactly, and the new eight-method
  sequence of a clean turn: `initialize, initialized, account/read,
  account/rateLimits/read, thread/start, turn/start, account/read,
  account/rateLimits/read`. `SIX` becomes `EIGHT` in every test that uses it.
- **P2.** `spend_faults` table:
  - credits `{false,false,null}`, `"0"`, `"0.00"` and `"-0"` accept;
  - `"0.01"`, `"1"`, `"-1"`, `"1e400"`, `"abc"`, a 33-character decimal, a
    non-string, `hasCredits` true, `unlimited` true, an absent `credits`, an
    error reply, a missing result, and a mismatched `planType` refuse;
  - an absent `planType` accepts;
  - **bucket selection**: a clean headline with a credit-bearing
    `rateLimitsByLimitId["codex"]` refuses; a credit-bearing headline (another
    bucket first) with a clean Codex entry accepts; a missing map, a missing
    `codex` key, and a `codex` key whose entry has `limitId` null or another
    id all refuse.
- **P3.** `spend_change_faults`: each of the five fields changing refuses, and
  a used-percent change accepts.
- **P4.** Field walk of the accepting outcome. A readback planted with an
  email, account ID, upsell, limit name and plan string publishes none of them
  anywhere (`assert_published_surfaces_are_bounded`). `rate_limit.detail` keys
  are exactly the fixed vocabulary, and `is_using_overage` is `None`.
- **P5.** Notifications:
  - `account/rateLimits/updated` with `planType` absent, null or `pro` in a
    `pro` binding: the turn succeeds, is counted as withheld, and none of its
    content appears in `raw`;
  - with `plus`, an extra params key, a non-object `rateLimits`, or a
    non-object `params`: refused;
  - `account/updated` and `account/login/completed` are refused, including in
    the callback path;
  - `account/x` is refused;
  - `modelProvider/authRecoveryStarted`, `…Completed` and `modelProvider/x`
    are refused, with a fault that names the method and nothing from
    `provider` or `message` (planted `Amazon Bedrock` never appears);
  - the accepting twin: a non-namespaced unknown notification is still
    withheld, not refused.
  - The old pin `test_the_pinned_rate_limit_notification_discards_the_turn`
    flips to these.
- **P6.** Conversation:
  - a pre-turn readback fault or error means exactly four methods, no
    `dynamicTools`, and an unavailable outcome (READ and WRITE);
  - a missing readback reply refuses;
  - a post-turn change discards the turn;
  - the accepting path succeeds and publishes the post-turn `rate_limit`;
  - scripted "expired login" (`account/read` clean, readback error) refuses
    before the turn.
- **P7.** Startup mode:
  - exactly four methods, and `gate_completed` only after the readback;
  - a `RecursionError` record during the readback gives `GATE_INCOMPLETE`;
  - after its readback it sends nothing more before closing stdin.
  - The handle never sets it: a handle-driven clean run sends `thread/start`,
    and a constructor spy sees `startup_only=False` on every construction.
- **P8.** `operator_store` and the handle:
  - `open_credential` accepts a regular `0600` file and refuses a symlink,
    directory, nlink 2, `0644`, another uid (substituted `fstat`) and an
    absent file;
  - it opens only `O_PATH`, relative to the store descriptor, never by path.
    This is pinned by recording the `openat` flags and base descriptor, and by
    a substituted `open` that raises;
  - the handle's `NativeStoreMount` carries the very descriptor that was
    checked (identity compared with `fstat`);
  - the configuration memfd is sealed before its digest is compared, and a
    substituted byte string fails the compare with no spawn;
  - both descriptors are closed after `exchange` returns and after it raises.
  - `StoreMaintenance.check()` is positive inside the context, and refuses
    after exit, after `active.json` is replaced, and after bundle substitution
    (the `StoreWorld` doubles);
  - the `check()` digest never equals a provider binding digest.
- **P9.** Lane with a substituted launcher and relay:
  - login evidence contains none of the planted stdout, even though the code
    reached `out`;
  - `completed` is written last, and a failure in `write_evidence` leaves no
    completed file;
  - any denial in a clean-expected run is a fault, and S6b's declared denial
    is not;
  - a run without all three refresh facts records `refresh: "unmeasured"`;
  - an evidence field walk refuses any string outside the closed vocabulary;
    a gate fault naming `'prolite'` is admitted, and a planted email is not;
  - `--hold` pauses after the readback is judged and never past the deadline;
  - a pre-existing `lane_dir` refuses.
- **P10.** Relay, per destination (portable relay tests with controlled
  peers):
  - `accepted:h:p` and `relayed:h:p` appear exactly once per event, and only
    for sealed destinations;
  - a peer that accepts but never writes gives accepted with no relayed;
  - a CONNECT to an unsealed, planted 253-character hostname raises
    `denied:destination` by one and adds **no** key containing any of its
    bytes;
  - the key set is always a subset of the policy's names;
  - the existing reason counters are unchanged.

**Linux (credential-free CI).**
- **L1.** In-zone layout probe:
  - `$CODEX_HOME` is exactly `/tmp/home/.codex`;
  - `auth.json` can be rewritten in place with harmless marker bytes, and the
    host-side store file shows them afterwards;
  - `rename` and `unlink` over it fail with `EBUSY`;
  - writing `config.toml` is denied (`EROFS` or `EACCES`, recorded);
  - `/vendor-store` is absent;
  - other files in the store directory are invisible;
  - a planted `auth.json` symlink is refused by `before_spawn`, with no spawn;
  - **descriptor binding:** after `before_spawn` opens the descriptor, the
    test substitutes the host path (renames a different regular `0600` file
    into place before bubblewrap runs, through a hook in the substituted
    spawn). The zone still sees the checked object, shown by its marker bytes.
    The configuration is the memfd's bytes, whatever is on any path;
  - host-visible inventory: after the run, the only host path changed is the
    store's `auth.json`. The zone's `log/` and state directories exist only in
    its tmpfs.

  The N3a and N3c zone proofs that wrote under `/vendor-store` move to the
  bound file. Their subjects (store persistence, non-widening, identity) are
  unchanged.
- **L2.** The pinned binary, the **production** configuration and no login
  (the startup lane):
  - the gate refuses with `NO_ACCOUNT_FAULT` only;
  - no readback and no `thread/start`;
  - **zero** relay denials of every reason, and zero accepted connections.
  - Control in the same step: the fixture's configuration (plugins on)
    produces `denied:destination` of at least 1, and the test's own head
    capture names `chatgpt.com:443` (section 7).
- **L3.** Pinned `codex login --device-auth` in a maintenance lane whose policy
  seals nothing (a decoy only):
  - `denied:destination` of at least 1 is recorded, and the test's head
    capture names `auth.openai.com:443`;
  - exit is non-zero;
  - the evidence has no stdout;
  - the placeholder is still present and regular, because `unlink` hit
    `EBUSY`.

  No vendor is reached.
- **L4.** A maintenance-held launch keeps the maintenance lock in the
  supervisor. A `publish_descriptor_offline(wait_s=0)` during the zone
  refuses, and after the reap it proceeds.

Retained inventories are rerun against every changed anchor: N2, N2 WRITE, N3a,
N3b, N3c and the N4 bridge. `uv run verify` runs with `PYTHONIOENCODING=utf-8`.

## Mutation inventory

These go in a new `scripts/check_m8_n4_mutations.py`. Each mutant must be
killed by assertion.

| # | Mutant | Killed by |
| --- | --- | --- |
| 1 | Admit every `account/` notice | P5 (`account/updated`) |
| 2 | Admit `rateLimits/updated` whatever its `planType` | P5 (`plus`) |
| 3 | Refuse `rateLimits/updated` always | P5 (accepting) |
| 4 | Drop the exact-params-keys check | P5 (extra key) |
| 5 | Admit `account/login/completed` | P5 |
| 6 | Callback path keeps the old namespace rule | P5 (callback variant) |
| 7 | Skip the pre-turn readback | P1, P6 |
| 8 | Treat a readback error as a pass | P6 |
| 9 | Admit `hasCredits: true` | P2 |
| 10 | Admit `unlimited: true` | P2 |
| 11 | `balance_zero` true for a non-zero value (`!= 0` becomes `>= 0`) | P2 (`"0.01"`, `"-1"`) |
| 12 | Absent `credits` admitted | P2 |
| 13 | Readback `planType` not compared | P2 |
| 14 | Skip the post-turn readback | P1, P6 |
| 15 | `spend_change_faults` ignores `has_credits` | P3 |
| 16 | `rate_limit` from the pre-turn reading only | P6 (accepting value) |
| 17 | `accountId` copied into `detail` | P4 |
| 18 | Startup mode continues to `thread/start` | P7 |
| 19 | `gate_completed` latched before the readback is judged | P7 (`RecursionError`) |
| 20 | The handle passes `startup_only=True` | P7 |
| 21 | Credential bound read-only | L1 (in-place write) |
| 22 | Whole store directory bound | L1 (`/vendor-store` absent, siblings invisible) |
| 23 | `config.toml` bound read/write | L1 |
| 24 | `CODEX_HOME` not set | L1 |
| 25 | `open_credential` without `O_NOFOLLOW` | P8 (symlink) |
| 26 | `open_credential` skips the nlink or mode check | P8 |
| 27 | Configuration memfd not compared with its digest, or compared before sealing | P8 (substituted bytes) |
| 28 | `StoreMaintenance.check()` does not reread `active.json` | P8 |
| 29 | `check()` positive after close | P8 |
| 30 | No per-destination accepted key | P10 |
| 31 | `relayed` counted before any upstream byte | P10 (silent peer) |
| 32 | A denial keyed by the attempted hostname | P10 (key set is sealed names only) |
| 33 | Lane evidence records stdout | P9 |
| 34 | `completed` written first | P9 |
| 35 | A denial in a clean-expected run not a fault | P9 |
| 36 | Missing refresh reported as passed | P9 |
| 37 | Credential bound by path, not by the checked descriptor | L1 (descriptor binding), P8 |
| 38 | Readback judges the headline `rateLimits` | P2 (bucket selection) |
| 39 | Readback accepts a `codex` entry whose `limitId` is null | P2 |
| 40 | `modelProvider/` withheld, not refused | P5 |
| 41 | Supervisor does not pass the mount descriptors to bubblewrap | L1 (launch fails if they are missing) |

Mutants 21-24, 37's L1 half and 41 are Linux-only and report NOT PROVEN on
Windows. That is expected, and they are not kills.

## Operator session runbook

This is one attended session. The owner completes the vendor sign-in, and no
agent handles a credential. Every step records bounded evidence. Any fault,
unexpected destination, `account/` change or refusal means: stop, record, do
not retry. The only exception is an intended refusal in S6.

- **S0. Preconditions** (#77 authorization list). Confirm each one, with links
  recorded in the PR:
  - N3c merged;
  - #73 qualification evidence recorded;
  - the `pre-m8-artifacts` checkpoint deleted under its own authorization;
  - the N4 implementation PR merged at commit C;
  - the runtime installed and verified at C (host-runtime interface);
  - `m8-host-drift` baseline passing.

  If any is missing, stop.
- **S1. Pin.** Resolve `auth.openai.com` and `chatgpt.com` once on the host and
  write the pin record. Build the login policy (`auth.openai.com:443`) and the
  startup policy (both hosts).
- **S2. First provisioning only.** Publish g1 (N3c procedure). Inside a
  maintenance context, create an empty `auth.json` with
  `install -m 0600 /dev/null <store>/auth.json`. A later re-login reuses the
  existing file.
- **S3. Login.** Inside `maintain_offline(...)`, run
  `codex_lane login --policy login`. The owner opens the printed URL on their
  own device and enters the one-time code. Record the evidence: exit status,
  relay record, credential metadata.
- **S4. Qualify, in the same context.** Run
  `codex_lane startup --custody maintenance --expected pro`. It sends only the
  four permitted methods. Record:
  - the gate verdict;
  - the seven readback fields;
  - the withheld notification names;
  - the relay record.

  If the plan refuses and names another literal (for example `'prolite'`),
  stop for owner decision (open question 1).
- **S5. Exit, publish g2.** The qualification evidence digest becomes the two
  conformance revisions of the production launch identity (N3c decision 3:
  operator input, now content-addressed).
- **S6. Controls.** Each one is an intended refusal, recorded as a pass only
  when it refuses.
  - **(a)** A startup lane holds the lock (`--hold` pauses before closing
    stdin, within the deadline), and `maintain_offline(wait_s=0)` refuses.
  - **(b)** Startup with a policy that has no `chatgpt.com`: the readback
    fails, the run refuses before any thread, and
    `denied:destination` of at least 1 is recorded. This denial is declared
    in advance, and it is the lane's live positive control for the
    zero-denial rule.
  - **(c)** Startup with `--expected plus`: refused, and the fault names the
    observed literal.

  (a) runs inside a fresh maintenance context. (b) and (c) run after S7 on the
  active path.
- **S7. Activate g2** with the qualified identity.
- **S8. Active-path startup.** Run `codex_lane startup --custody active` through
  `BindingStore`. It must accept. Then `BindingStore` sealed at g1 refuses
  (generation invalidation).
- **S9. Restart.**
  1. Stop and start the VM.
  2. Every provider and helper refuses until maintenance runs (N3c decision 7).
  3. `maintain_offline`, which re-anchors, then S4 qualification with no
     login, then exit.
  4. Publish g3 and activate g3.
  5. Active-path startup accepts, and g2 refuses.
  6. Record whether the S1 pins still served: the readback was judged through
     them, with `relayed` as corroboration only.
- **S10. Refresh, scheduled.** At least 24 hours after S3, still inside this
  authorization, run an active-path startup. Refresh counts as **measured**
  only when all three hold in that run:
  - `accepted:auth.openai.com:443` is above zero;
  - `mtime_changed` is true;
  - the readback is judged clean.

  Even then, the record claims only what the run proves: which vendor manager
  refreshed is not attributed (Limits). Otherwise refresh is **unmeasured**,
  and the profile stays unqualified until a later run measures it.

Evidence goes in the PR and the implementation record only. None of it
contains a token, credential content, account identifier, email, device code,
stdout, or a hostname outside the sealed policy. A plan string appears only as
the closed-alphabet literal that a refusal fault names (section 5).

## Host-runtime interface required

This is what this design needs from the parallel host-runtime installation.
Nothing else is assumed.

1. The immutable runtime root (`LinuxLauncher.root`, digest-verified) contains:
   - the pinned `codex` binary (SHA-256 `56ef98ab…62da`);
   - `/usr/libexec/constructicon-egress-bridge.py`;
   - the supervisor, at the N4 revision (`--mount-fds`);
   - `/usr/bin/python3`;
   - the **fixed model catalog JSON** at one fixed absolute path, which the
     sealed configuration names in `model_catalog_json`.

   It must **not** contain `/etc/codex`.
2. The M8-D2 AppArmor profiles are loaded, and bubblewrap is
   `0.9.0-1ubuntu0.3`. That package must provide `--bind-fd` and
   `--ro-bind-data`; this is to be confirmed before implementation (section 1).
   The profiles must permit descriptor-sourced mounts.
3. The `constructicon` package at commit C is importable by the service user's
   interpreter (never root), with the entry point
   `python -I -m constructicon.substrate.executors.codex_lane`.
4. The operator-store bundle is provisioned as N3a/N3c specify. The service
   user runs every lane and every offline helper.
5. A service-user-writable lane root that is short enough for the relay socket
   path, and a separate evidence directory.
6. Host resolver access for S1, outside any zone.

## Limits carried

**To N5 (turns):**
- **Model-session egress.** Destinations and TLS are unobserved, whether
  HTTPS/SSE or websocket (websocket is source-only). `chatgpt.com` is already
  sealed, so a model request on it is indistinguishable at the relay.
- **Turn evidence.** The `item/` allowlist, the contents of turn payloads,
  and `model/rerouted` against `served_model`.
- **Forward cost.** A legitimate refresh after a 401 during a turn emits
  `modelProvider/authRecovery*`, which now refuses and discards the turn.
  The first occurrence names itself in the fault.
- **Spend.**
  - The balance "can go negative" within one turn (#78 research).
  - Automatic reload is not observable in the client, so the operator attests
    it and re-captures it before N5.
  - Only the bucket whose own `limitId` is `codex` is judged. If the vendor
    omits that id, the readback refuses, and N5 stops.
  - Mid-turn `rateLimits/updated` spend fields are not judged. The post-turn
    readback judges the resulting state.
- **Address stability.** CDN address staleness during a turn fails the turn;
  it never widens egress.
- **Stderr.** The contents of `evidence_excerpt` are not qualified. N4 records
  only the stderr byte count.

**From N4's own design:**
- **Effective configuration** is not read back live, because `config/read` is
  not authorized. It is fixed by construction: strict configuration, a
  read-only file, no system layer, and no cloud layer for the expected plan.
- **Cloud layer.** For an eligible plan, the vendor applies the layer at
  startup, before the gate. The gate refuses that plan before any thread
  exists, but what the layer would do before the gate is not proved empty. It
  is excluded only because the expected plan is ineligible.
- **Connection attribution.** Authenticated auxiliary requests to
  `chatgpt.com` over an accepted connection cannot be attributed (HTTP/2). Their
  absence rests on source gates and L2's credential-free control.
- **Refresh concurrency and attribution.** Two `AuthManager` instances
  refresh independently (`app-server/src/lib.rs:509-512, 758-761`), and `save`
  takes no file lock. So two in-place saves could interleave. Store damage is
  seen only on a later run, as a refusal that requires maintenance. It is not
  seen in the current run. A measured refresh proves a connection, a write and
  a clean readback in one run. It does not prove which manager refreshed, or
  that the readback used the new credentials.
- **Qualification before activation** stays operator-asserted (N3c decision
  3). The evidence digest in the launch identity names the evidence, but
  activation does not verify it.
- **Trusted custody.** A same-uid host process between qualification and
  activation is covered by the trusted-custody boundary (N3c), not by
  detection.
- **`relayed`** means only that bytes were relayed. It makes no claim about
  TLS or the endpoint.
- **Plan literal.** Which `PlanType` literal Pro 20x reports is observed at S4
  and not predicted.

## Rejected as unnecessary

- **A `qualify_offline` helper.** Qualification inside the maintenance context
  gets the same floor-based invalidation. Neither form would prove that
  activation followed a qualification without a new durable field (section 5).
- **A symlink from `CODEX_HOME` into a directory mount.** Login loses the
  credential (Inputs 3).
- **Keeping `/vendor-store` next to the file bind.** That keeps write access
  the client never uses.
- **A configurable spend bound.** The owner's bound is fixed in code, and a
  change is a new revision.
- **Parsing `rateLimitResetCredits`, `individualLimit` or any bucket other
  than `codex`.** No bound uses them.
- **Recording attempted hostnames of denied connections.** That was withdrawn
  after review: it is a covert channel into evidence.
- **Path-based binds with re-checks.** Replaced by descriptor binds.
- **A new L0 field, a journal record, or runtime maintenance and
  qualification APIs.**
- **Reading `auth.json` to detect login or refresh.** ADR 0021 forbids it.
  Metadata and relay facts are enough.

## Orchestrator decisions (2026-09-24, before implementation)

The questions below are kept as they were asked. These are the decisions, and
they supersede the design text above wherever the two differ.

1. **Expected plan literal: bound at qualification, never guessed.** The
   pinned `PlanType` has both `pro` and `prolite`, and nothing proves which
   one "ChatGPT Pro 20x" reports.
   - The first authenticated `account/read` in the owner-attended maintenance
     session (runbook S4) must report a plan in `{pro, prolite}`. Anything
     else stops the session.
   - The observed literal is recorded in the qualification evidence and
     becomes the sealed expected plan for that generation.
   - Any later run that observes a different plan refuses. A plan change is a
     mode change and requires new maintenance.
   - If S4 refuses in the owner session: stop, report the observed literal to
     the orchestrator, and take no fallback.

   The runbook's `--expected pro` becomes "the qualification run accepts
   `{pro, prolite}` and records the literal; every later run expects that
   recorded literal".
2. **Section 7:** resolved. The path is traced and disabled at the source,
   and no denial is tolerated.
3. **The layout move is a preparatory PR.** It covers the narrow
   `CODEX_HOME` layout (tmpfs home, sealed memfd configuration, fd-bound
   `auth.json`, `/vendor-store` removed) and moves the N3a/N3c zone proofs
   onto it, with its own CI evidence. It stays strictly to the layout, on
   `m8/n4-layout`, and this lane stacks on it. It is implemented as `37db228`;
   see the implementation record's "N4 preparation: narrow native layout".
4. **S10 refresh.** If refresh cannot be measured, the profile stays
   unqualified (`vendor_conformance_qualified` false) and S10 is recorded as
   open. That does not block merging N4's evidence.
5. **No new durable field** (YAGNI). The lane's evidence digest is passed
   inside the conformance revision string already given to
   `activate_offline`. The limit is recorded: activation does not itself
   verify it.
6. **Bubblewrap flags: resolved.** The pinned bubblewrap (SHA-256
   `e3189038…`, `0.9.0-1ubuntu0.3`) contains `--bind-fd`, `--ro-bind-fd`,
   `--bind-data` and `--ro-bind-data` (from the strings of the pinned binary).
   Linux CI still has to prove the behaviour.

## Review disposition

One Codex pass (`gpt-5.6-terra`, effort high, job `job_874f14f36992`, on
`a2b2004`). The verdict was "do not implement": five P1 and seven P2. The
pinned tree was readable to the reviewer, and the #77/#78 content was
unverified for it.
- Every premise was reproduced against source before it was acted on.
- The orchestrator's dispositions are applied as recorded.
- There was no second round, so the amendments are not re-reviewed.

| Finding | Class | Reproduced | Disposition |
| --- | --- | --- | --- |
| P1: the configuration file in the payload directory collides with the relay's fresh `mkdir` | introduced | `egress.py:486-487` (`mkdir` with no `exist_ok`), `codex.py:1570` | **Accepted.** The configuration is a sealed memfd bound with `--ro-bind-data`. There is no file, so no collision and nothing to dispose. Lifecycle rows added |
| P1 C4: the headline `rateLimits` may be an unrelated bucket | introduced | `account_processor.rs:1164-1181`, which also maps an id-less snapshot to `codex` | **Accepted.** Only the map entry whose own `limitId` is `codex` is judged. If it is absent, the run stops. Mutants 38-39 |
| P1 C7: the floor does not prove that qualification preceded activation | pre-existing, overclaimed here | `operator_store.py:1176-1184`; N3c decision 3 | **Accepted.** The claim is withdrawn and the limit stated. The conformance revisions are the evidence digest, so the identity names the evidence, but activation does not verify it (open question 5) |
| P1 C3: a path check with `lstat`, then a path bind, is check-to-use | introduced | `linux.py:466-474, 608-621`; the supervisor's `close_fds=True` at `_supervisor.py:137` | **Accepted.** An `O_PATH` descriptor is taken relative to the checked store descriptor and bound with `--bind-fd`. The supervisor passes both mount descriptors. Mutants 37 and 41, and L1's substitution test |
| P1 C6: `modelProvider/authRecovery*` withheld | introduced | `common.rs:1920-1921`; `transport_tests.rs:196-210` (Bedrock) | **Accepted.** The whole `modelProvider/` namespace refuses. The forward cost is recorded. Mutant 40 |
| P2: `answered` is not a TLS or endpoint fact | introduced | `egress.py:672-690` | **Accepted.** Renamed `relayed` and described as bytes relayed only. The CDN finding rests on the client's own request succeeding |
| P2: denied hostnames retained | introduced | `egress.py:204-227, 642-647` | **Accepted.** Denials are counted by reason only, and only sealed names are keyed. Mutant 32 was rewritten |
| P2: `codex-login.log` and other `CODEX_HOME` content not inventoried | introduced | `cli/src/login.rs:48-113, 325`; `core/src/config/mod.rs:906-907` | **Accepted.** Exact inventory: two host-originated files, everything else disposable in the zone tmpfs. L1 checks the host-visible paths |
| P2: refresh not attributable | introduced | `storage.rs:206-222`; `manager.rs:2345-2358`; two managers at `lib.rs:509-512, 758-761` | **Accepted as a stated limit.** The refresh row claims only connection, write and clean readback in one run |
| P2: lifecycle omissions (configuration, relay directory, evidence write, refresh race) | introduced | as listed | **Accepted.** Rows added to the lifecycle walk |
| P2: plan literal contradiction; `--hold` undefined | introduced | design text | **Accepted.** Plan literals appear only as `named_value` fault literals. `--hold` is defined, bounded and tested (P9) |
| P2: identity consequences incomplete | introduced | `linux.py:305-315`; `codex.py:195, 257-265, 1793-1800` | **Accepted.** An identity table was added. No earlier conformance evidence carries over |

**Also folded in:** the orchestrator's decision on the traced
`CONNECT chatgpt.com:443` (section 7), and the source census (section 1).
Nothing was rejected.
