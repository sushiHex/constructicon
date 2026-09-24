# M8 N4: authenticated startup, state and resume review

Status: pre-implementation design. It has not been independently reviewed yet
(see [Review disposition](#review-disposition)).
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

1. **Narrow layout.** The native zone's `CODEX_HOME` is a fresh tmpfs
   directory. It holds exactly two things:
   - the sealed configuration, bound read-only;
   - the store's `auth.json`, bound read/write as a single file.

   The store directory is no longer mounted. Today nothing delivers the
   sealed configuration to the client, and nothing routes the credential to
   it (Inputs, rows 1 and 2). N4 cannot start without both.
2. **One conversation, one boundary.** The existing conversation gains an
   `account/rateLimits/read` readback:
   - once after the pre-turn mode gate, before `thread/start`;
   - once after the pre-acceptance reading.

   N4's startup lane is the same conversation, stopped right after the first
   readback. It never sends `thread/start`, so it makes exactly the four
   authorized requests.
3. **The readback is judged, not just recorded.** Before the turn it must show
   the plan the binding expects and no purchased credits, which is the owner's
   N5 bound, written as code. After the turn, its overage fields must equal the
   pre-turn values. The post-turn reading becomes the outcome's `rate_limit`.
   Only a fixed set of numeric and boolean fields is published; account ID,
   plan and upsell are never published.
4. **Account notifications move from a namespace to an allowlist.** The pin
   emits exactly three `account/` notifications. Only
   `account/rateLimits/updated` is admitted, and only when its `planType` is
   absent or equals the expected plan. Every other `account/` method still
   refuses.
5. **The relay records per destination.** It records `(host, port)` for every
   accepted, answered and destination-denied connection. The number of keys is
   bounded by the connection bound that already exists.
6. **Launches held under maintenance.** The maintenance context exposes its
   lock and one positive check. The operator's login, and the qualification
   startup run just after it, both run in the real zone behind the relay while
   the maintenance lock is held. Qualification therefore happens before the
   next generation is published. The floor from N3c makes a later re-login
   invalidate it mechanically.
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
     `{threadId, turnId, provider, message}` (`v2/notification.rs:11-16`). The
     turn-evidence allowlist already withholds them (`codex_protocol.py:546-547`).
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
   reports from `auth_cached()` and makes no call of its own (trace:
   `account_processor.rs:1019-1032`). An expired or revoked login therefore still
   reads as a ChatGPT `pro` account. The readback is the first request that
   exercises the credential.
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
    **stderr** (`device_code_auth.rs:158-163`; `cli/src/login.rs:354-362`).
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

**`linux.py`, `LinuxLauncher.argv`.** When `native_store` is given, the one
`--bind <store> /vendor-store` is replaced by:

```text
--dir /tmp/home/.codex
--ro-bind <configuration file> /tmp/home/.codex/config.toml
--bind <store>/auth.json /tmp/home/.codex/auth.json
--setenv CODEX_HOME /tmp/home/.codex
```

- `NativeStoreMount` gains one field, `configuration: Path`. It still carries
  no mount catalogue: both zone paths are constants in `linux.py`, and the file
  name comes from `operator_store.CREDENTIAL_FILE`.
- The egress leaf and the bridge prefix are unchanged.
- `CODEX_HOME` is set explicitly even though it equals the default. That keeps
  routing independent of `HOME`.

**`operator_store.py`.**
- `CREDENTIAL_FILE = "auth.json"`.
- `credential_file(store_path) -> Path` checks the file with `lstat` and never
  opens it:
  - a regular file, not a symlink;
  - `st_nlink == 1`;
  - `st_uid == os.getuid()`;
  - mode exactly `0600`.

  Anything else, including absence, raises `ContractViolation("the operator
  store has no qualified credential file")`. The function reads no content and
  hashes nothing (ADR 0021:171-174).
- Both constants live in this module, so `BINDING_LAYOUT_LAW`, which digests
  the module source (`operator_store.py:1265-1266`), now covers the layout.
  Every existing descriptor then refuses until it is republished. That was
  already the rule for any `operator_store.py` edit.

**`codex.py`, the handle.**
- The provider retains its `configuration` string.
- `_converse` writes it to `<acquisition payload>/config.toml`, where the
  egress socket already lives:
  - created with `O_CREAT | O_EXCL | O_NOFOLLOW`, mode `0400`;
  - checked before close by comparing the digest of the written bytes with
    `identity.configuration_digest`;
  - removed when the acquisition's scratch is disposed.
- `before_spawn` adds `credential_file(held.store_path)` before its binding
  check.

**Why a single-file bind.**
- `rename` and `unlink` over a bind mount fail with `EBUSY`. A zone can
  therefore never replace, delete or symlink the credential. It also cannot
  reach any other store content, which it can today through `/vendor-store`.
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

  It reads only `result.rateLimits`. `accountId`, `rateLimitUpsell`,
  `rateLimitsByLimitId`, `rateLimitResetCredits`, `limitId`, `limitName` and
  `individualLimit` are never read. It returns `None` for an error reply or a
  missing result.
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

**Outside the namespace.** `modelProvider/authRecovery*` (Inputs 4) stays
withheld and does not refuse.
- A recovery is a refresh after a 401, which ADR 0021 permits (lines 212-215).
  It cannot change the authentication mode by itself.
- Any plan or mode it produces is seen by the pre-acceptance reading, the
  post-turn readback, or a later `account/rateLimits/updated`.
- This is recorded, not built: turns are N5.

### 4. Per-destination relay evidence (`egress.py`)

In `EgressRelay`, and nowhere else:

- `_open`: before raising the destination denial, record
  `observed[f"denied:destination:{host}:{port}"] += 1`. The existing `denied:destination` counter is kept, so current tests and consumers are unchanged.
- `_handle`: next to `accepted`, record `observed[f"accepted:{host}:{port}"]`.
  This needs `_open` to return the destination alongside the socket.
- `_pump`, upstream to client: on the first non-empty chunk only, record
  `observed[f"answered:{host}:{port}"] += 1`. This is the positive fact that
  the pinned address really served TLS bytes, which is what CDN qualification
  needs. A connection that is accepted but never answered is a stale-address
  signal, not a pass.

The host has already passed `parse_connect`'s DNS grammar: lower case, at most
253 characters (`egress.py:80-94, 204-227`). Nothing unparsed is keyed.
- Keys are bounded because each key needs one handled connection, and handled
  connections are bounded by `policy.connections` (Inputs 11).
- Hostnames are within the owner's evidence retention ("destination
  hostnames").
- This changes `enforcement_build_digest`, because it digests the module
  source (`egress.py:180-182`). The N4 egress identity is new in any case.

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
login**, and before the next generation is published. This design choice
replaces a new `qualify_offline` helper.
- **Why this is sound.** Every descriptor is published after the withdrawal:
  publication takes the lock, and the floor is the highest descriptor at
  maintenance time. So "activate g only if g is above the floor" already
  proves that no maintenance, and so no re-login, happened between that
  qualification and g's publication. A second maintenance raises the floor to
  at least g, which makes g impossible to activate (N3c S-tests).
- **Why ADR 0021:195-197 is met.** Qualification is completed before the
  atomic activation.
- **The residual.** A same-uid host process could edit the store between the
  two. That is the existing trusted-custody limit (N3c).
- **Why not activate first and qualify through the provider.** ADR 0021:195-197
  forbids activation before qualification.

**Lane module: `substrate/executors/codex_lane.py`.** It is new, and it
composes existing parts only.

- `async run_login(maintenance, launcher, policy, *, binary, configuration,
  deadline, out) -> LaneEvidence`. It:
  - runs `codex login --device-auth` through `LinuxLauncher.exchange`;
  - passes a `NativeStoreMount(path=maintenance.store_path,
    lock_fd=maintenance.lock_fd, configuration=…, before_spawn=…)`, where
    `before_spawn` runs `credential_file(...)` and then `maintenance.check()`;
  - uses `guard_fds=(maintenance.lock_fd,)`;
  - wraps the launch in `EgressRelay(policy, lane_dir, deadline, check)`.

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
- `main(argv)` is a thin argument parser for the host operator, with the
  subcommands `login`, `startup` and `refused-destinations`. It does no
  interactive prompting of its own.

`lane_dir` is a fresh `0700` directory under an operator-given root. It holds
the relay socket and `config.toml`, and is removed at exit. Its path length is
checked with the provider's existing rule (`codex.py:1843-1849`).

**Stop rules in the lane, mechanically.**
- A relay denial for a destination is compared with the lane's
  `expected_refused` set, which is empty unless section 7's outcome A fills it.
  Any other denied destination adds the fault "an unexpected destination was
  attempted".
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
relay {accepted:{h:p:n}, answered:{…}, denied:{reason|destination:h:p: n}},
credential {present, regular_0600, mtime_changed},
process {returncode, payload_returncode, timed_out, elapsed_s, stderr_bytes},
completed
```

It never holds stdout, stderr text, an email, account ID, token, device code,
plan string, file content or content hash. `mtime_changed` compares the `lstat`
before and after the run, which is metadata only.

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
     or as accepted but never `answered`.
   - The client's request then fails, and the conversation refuses (a readback
     error, or no reply).
   - The operator never re-resolves inside a run. Re-pinning is a new egress
     identity and therefore requalification.
4. **What N4 measures.** Whether one pin served the login, the qualification
   and the restart run hours later: an `answered` count above zero on each run,
   and the address unchanged between records. This is the "CDN address
   practicality" finding. N4 neither claims nor needs address stability during
   a model turn (see Limits).

### 7. The unsolicited `CONNECT chatgpt.com:443` (slot)

> **SLOT: awaiting the separate trace.** The bridge CI run recorded this
> CONNECT with no login and no model request, and with no `user-agent` line
> (implementation record, "An unsolicited startup connection"). It was made
> under the test fixture's configuration, which leaves `plugins` at its
> default of on.
>
> An unverified candidate from this review: the plugin featured-IDs warm-up.
> It sits inside `if config.plugins_enabled`, and "sent even without ChatGPT
> auth" (`core-plugins/src/manager.rs:2845-2858`, trace). The traced code path
> replaces this paragraph.

N4 seals `chatgpt.com:443` for the readback, so the relay can no longer refuse
this CONNECT by destination. The two outcomes are designed as follows.

- **A. The path is configuration-gated** (for example, `plugins = false`).
  - The sealed configuration disables it, and the source gate is cited.
  - The proof is L2, credential-free and with a same-run control:
    - The pinned binary with the **production** configuration and no login
      makes **zero** CONNECT heads. With no login, the readback is never
      reached, because the gate refuses first.
    - The same run with the fixture's configuration records the
      `chatgpt.com:443` head. That shows the recorder would have seen it.
  - With a login, an accepted connection cannot be attributed to a request,
    because HTTP/2 multiplexes. So authenticated absence rests on the gate and
    the control, not on connection counts. This is recorded as a limit.
- **B. The path is not configuration-gated.**
  - If its host is outside the sealed set, the relay refuses it. The lane's
    `expected_refused` names exactly that `(host, port)` with its traced
    file:line, and any other refusal still stops the run. L2 pins the head.
  - If its host is `chatgpt.com`, it is accepted by construction. It then
    qualifies only if source shows its response cannot widen tools, helpers,
    destinations, mounts or writes, and runs before or without any model
    request. Otherwise the profile is **unavailable** (ADR 0021:282-284:
    "startup must be proved within the declared restriction or refused").
    Widening the policy is never the answer.

### 8. Authority-input inventory (pinned client, startup phase)

| Input | Disposition | Proof |
| --- | --- | --- |
| `config.toml` in `CODEX_HOME` | **Fixed and revision-bound**: the sealed bytes, bound read-only, their digest checked against the launch identity before spawn | L1 (read-only), P8 |
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

Tools and callbacks do not exist before `thread/start`. N2 and N3 own their
identity-independent confinement, and N4 does not re-prove it.

### What does not change

The following are all unchanged:
- the grant predicate, the profile, and the identity records (no L0 edit);
- the lease and journal;
- the walker;
- the WRITE callback path;
- the relay's policy, rules and deadline;
- the supervisor and the bridge;
- the provider's availability law. `vendor_conformance_qualified` stays false,
  and default production unavailability stays.

The adapter's fixed `clientInfo` is also unchanged.

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
| `EgressRelay.__aenter__` | Socket bound in `lane_dir` | Controller death takes the relay with it. The zone never starts |
| `launcher.exchange`, then `before_spawn` | Credential file checked; `maintenance.check()` positive; synchronous, immediately before spawn | A placeholder that was not created, or a replaced `active.json`, refuses with no spawn |
| Conversation reads stdout | The code has been shown to the operator, who signs in on their own device | Controller death: the supervisor keeps the lock until the zone is reaped (N3a owner-death). The vendor may have truncated `auth.json`. The binding stays withdrawn |
| Login exits | `auth.json` has been rewritten in place | The lane records the exit status, relay record and credential metadata |
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
| "No unexpected destination" from no denials | A per-destination accepted, answered and denied record; a closed `expected_refused` set; and a control run showing the recorder records |
| "Login worked" from exit 0 | Exit 0, **and** the credential file is regular `0600` with `mtime_changed`, **and** the following qualification gate accepts plan `pro` |
| "No model request" from no model traffic | `methods_sent` equals exactly the four methods, `startup_only` is set, and `gate_completed` is latched after the readback. An egress record cannot separate phases on a shared host, and this is not claimed |
| "Within the spend bound" from no credits field | An absent `credits` object refuses. `balance_zero` is `True` only after a parse succeeds |
| "The readback ran" from no readback fault | `gate_completed` is set only after `spend_faults` returns, and the evidence stores the reading's fields |
| "The credential file is the store's" from a bind that did not error | `lstat` checks regular, nlink 1, uid and `0600` at `before_spawn` |
| "Refresh works" from no refresh failure | `accepted:auth.openai.com:443` above zero and `mtime_changed`. Otherwise the row is recorded as **unmeasured**, and the profile stays unqualified (criterion 5) |
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
  - an absent `planType` accepts.
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
  - `modelProvider/authRecoveryCompleted` is withheld and not refused.
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
- **P8.** `operator_store`:
  - `credential_file` accepts a regular `0600` file and refuses a symlink,
    directory, nlink 2, `0644`, another uid (substituted `lstat`), and an
    absent file;
  - it never opens the file, pinned by substituting `os.open` and `open` to
    raise.
  - `StoreMaintenance.check()` is positive inside the context, and refuses
    after exit, after `active.json` is replaced, and after bundle substitution
    (the `StoreWorld` doubles);
  - the `check()` digest never equals a provider binding digest.
- **P9.** Lane with a substituted launcher and relay:
  - login evidence contains none of the planted stdout, even though the code
    reached `out`;
  - `completed` is written last, and a failure in `write_evidence` leaves no
    completed file;
  - an unexpected denied destination is a fault, and an `expected_refused` one
    is not;
  - a run without refresh records `refresh: "unmeasured"`;
  - an evidence field walk refuses any string outside the closed vocabulary.
- **P10.** Relay, per destination (portable relay tests with controlled
  peers): `accepted:h:p`, `answered:h:p` and `denied:destination:h:p` each
  appear exactly once per event. A peer that accepts but never writes gives
  accepted with no answered. With `connections=2` and five attempts, there are
  at most two per-destination keys. The existing reason counters are
  unchanged.

**Linux (credential-free CI).**
- **L1.** In-zone layout probe:
  - `$CODEX_HOME` is exactly `/tmp/home/.codex`;
  - `auth.json` can be rewritten in place with harmless marker bytes, and the
    host-side store file shows them afterwards;
  - `rename` and `unlink` over it fail with `EBUSY`;
  - writing `config.toml` is denied (`EROFS` or `EACCES`, recorded);
  - `/vendor-store` is absent;
  - other files in the store directory are invisible;
  - a planted `auth.json` symlink is refused by `before_spawn`, with no spawn.

  The N3a and N3c zone proofs that wrote under `/vendor-store` move to the
  bound file. Their subjects (store persistence, non-widening, identity) are
  unchanged.
- **L2.** The pinned binary, the **production** configuration and no login
  (the startup lane):
  - the gate refuses with `NO_ACCOUNT_FAULT` only;
  - no readback and no `thread/start`;
  - relay heads **zero**.
  - Control in the same step: the fixture's configuration shows the
    `chatgpt.com:443` head (section 7).
- **L3.** Pinned `codex login --device-auth` in a maintenance lane whose policy
  seals nothing (a decoy only):
  - `denied:destination:auth.openai.com:443` is recorded;
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
| 25 | `credential_file` follows symlinks (`stat` instead of `lstat`) | P8 |
| 26 | `credential_file` skips the nlink or mode check | P8 |
| 27 | Written configuration not compared with its digest | P8 (substituted bytes) |
| 28 | `StoreMaintenance.check()` does not reread `active.json` | P8 |
| 29 | `check()` positive after close | P8 |
| 30 | No per-destination accepted key | P10 |
| 31 | `answered` counted before any upstream byte | P10 (silent peer) |
| 32 | Destination-denial key omitted | P10, L3 |
| 33 | Lane evidence records stdout | P9 |
| 34 | `completed` written first | P9 |
| 35 | Unexpected denied destination not a fault | P9 |
| 36 | Missing refresh reported as passed | P9 |

Mutants 21-24 and 32's L3 half are Linux-only and report NOT PROVEN on
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
    `denied:destination:chatgpt.com:443` is recorded.
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
  6. Record whether the S1 pins still `answered`.
- **S10. Refresh, scheduled.** At least 24 hours after S3, still inside this
  authorization, run an active-path startup. Refresh counts as **measured**
  when `accepted:auth.openai.com:443` is above zero and `mtime_changed` is
  true. Otherwise it is **unmeasured**, and the profile stays unqualified until
  a later run measures it.

Evidence goes in the PR and the implementation record only. None of it
contains a token, credential content, account identifier, email, plan string,
device code or stdout.

## Host-runtime interface required

This is what this design needs from the parallel host-runtime installation.
Nothing else is assumed.

1. The immutable runtime root (`LinuxLauncher.root`, digest-verified) contains:
   - the pinned `codex` binary (SHA-256 `56ef98ab…62da`);
   - `/usr/libexec/constructicon-egress-bridge.py`;
   - the supervisor;
   - `/usr/bin/python3`;
   - the **fixed model catalog JSON** at one fixed absolute path, which the
     sealed configuration names in `model_catalog_json`.

   It must **not** contain `/etc/codex`.
2. The M8-D2 AppArmor profiles are loaded, and bubblewrap is `0.9.0-1ubuntu0.3`.
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
  `model/rerouted` against `served_model`, and `modelProvider/authRecovery*`
  during a turn.
- **Spend.**
  - The balance "can go negative" within one turn (#78 research).
  - Automatic reload is not observable in the client, so the operator attests
    it and re-captures it before N5.
  - Only the `codex` bucket is judged; `rateLimitsByLimitId` is not.
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
- **Refresh concurrency.** Two `AuthManager` instances refresh independently
  (trace), so two in-place saves could interleave. Store damage then refuses
  and requires maintenance.
- **Trusted custody.** A same-uid host process between qualification and
  activation is covered by the trusted-custody boundary (N3c), not by
  detection.
- **Plan literal.** Which `PlanType` literal Pro 20x reports is observed at S4
  and not predicted.

## Rejected as unnecessary

- **A `qualify_offline` helper.** Qualification inside the maintenance context
  gives the same guarantee with the existing floor (section 5).
- **A symlink from `CODEX_HOME` into a directory mount.** Login loses the
  credential (Inputs 3).
- **Keeping `/vendor-store` next to the file bind.** That keeps write access
  the client never uses.
- **A configurable spend bound.** The owner's bound is fixed in code, and a
  change is a new revision.
- **Parsing `rateLimitsByLimitId`, `rateLimitResetCredits` or
  `individualLimit`.** No bound uses them.
- **Refusing `modelProvider/authRecovery*`.** Refresh is permitted, and the
  mode is re-read.
- **A new L0 field, a journal record, or runtime maintenance and
  qualification APIs.**
- **Reading `auth.json` to detect login or refresh.** ADR 0021 forbids it.
  Metadata and relay facts are enough.

## Open questions for the orchestrator

1. **Expected plan literal.** Is it `pro`? The pin has both `pro` and
   `prolite`. If S4 refuses naming `prolite`, may the owner re-declare the
   binding's expected plan and repeat S4 as a new maintenance, or does that
   need a fresh decision?
2. **Section 7.** The trace outcome decides whether the lane's
   `expected_refused` stays empty.
3. **L1's ripple.** Moving the N3a and N3c zone proofs from `/vendor-store` to
   the bound file changes Linux-only tests in five files. Is that acceptable
   in the N4 PR, or should it be a preparatory PR?
4. **S10's timing.** Refresh may not occur within 24 hours. Should the profile
   stay unqualified until it is measured (this design), or should the owner
   accept an explicitly unmeasured refresh row?

## Review disposition

Pending: one Codex pass on this design.
