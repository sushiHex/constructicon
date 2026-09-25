# Codex ChatGPT-login token refresh at the pin

Research input for N4 (#77) and its S10 refresh run, not qualification.
Retrieved 2026-09-25. Source is tag `rust-v0.153.4`, commit
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`, the pin the repository cites. Paths
are under `codex-rs/` at that commit. Vendor pages were fetched with `curl` and
tag stripping. No login, credential or model call was made.

**The question:** does the owner's device login have to happen before every
run? **No.** One login persists in the store's `auth.json`, and the client
renews it during use. How long a binding survives without use is set by the
server and is not documented. S10 is the measurement.

## When the client refreshes

- **Lazily, on use.** `AuthManager::auth()` (`login/src/auth/manager.rs:2344-2359`)
  is the accessor every credential consumer calls. It refreshes first when
  `should_refresh_proactively` holds (`manager.rs:2924-2946`):
  - the access token's JWT `exp` is within
    `CHATGPT_ACCESS_TOKEN_REFRESH_WINDOW_MINUTES = 5` (`manager.rs:189`), the
    normal path; or
  - the token has no parseable `exp` and `last_refresh` is older than
    `TOKEN_REFRESH_INTERVAL = 8` days (`manager.rs:188`), the fallback.

  Tests `login/tests/suite/auth_refresh.rs` pin both edges (4 minutes out
  refreshes, 6 does not; 9 days refreshes, 1 does not).
- **Reactively, on a 401.** `UnauthorizedRecovery` (`manager.rs:1840-1911`)
  first reloads `auth.json`, then refreshes, then lets the error surface.
- **Never while idle.** No timer or interval calls `auth()` in `core/src` or
  `app-server/src`. A binding nobody uses is never renewed.

## How it refreshes

- `POST https://auth.openai.com/oauth/token` with
  `grant_type=refresh_token` (`manager.rs:197, 1583-1634, 1693-1698`). The
  lane already counts `accepted:auth.openai.com:443` as a refresh fact
  (`codex_lane.py`, `REFRESH_DESTINATION`).
- **Rotation is server-driven.** `persist_tokens` replaces the refresh token
  only when the response carries one (`manager.rs:1555-1579`). The upstream
  test shows the real response does carry one.
- **The save is in place, not by rename.** `FileAuthStorage::save`
  (`login/src/auth/storage.rs:206-223`) opens `auth.json` with truncate, write
  and create, writes, and flushes. That is the write a descriptor-bound file
  supports, which is why N4 binds one file (state review, section 1, item 3).
  The sealed configuration forces this backend with
  `cli_auth_credentials_store = "file"`.
- **No cross-process lock.** The only serialization is an in-process
  semaphore per `AuthManager` (`manager.rs:2045, 2769, 2808`). Upstream reports
  of rotated tokens invalidating a sibling process (openai/codex#26303) fit
  that. The store's retained lock gives each acquisition one vendor process.
  The two managers inside one app-server remain unserialized, a limit the
  state review already records ("Refresh concurrency and attribution").

## When refresh fails

`classify_refresh_token_failure` (`manager.rs:1636-1665`) maps
`refresh_token_expired`, `refresh_token_reused` and
`refresh_token_invalidated` to permanent failures. Each surfaces a fixed
message ending "Please log out and sign in again" (`manager.rs:191-195`). The
failure is cached for that auth snapshot, so the endpoint is not retried
(`manager.rs:2503-2518`). There is no automatic re-login and no API-key
fallback; openai/codex#44579 shows exactly this at 0.153.4. For N4 that is a
lane refusal and a maintenance login, never a silent change of account or
payer.

## Lifetime: not documented

- The client holds no refresh-token lifetime. `auth.openai.com` enforces it.
- The vendor's Codex authentication page says only: *"For sign in with
  ChatGPT sessions, Codex refreshes tokens automatically during use before
  they expire, so active sessions usually continue without requiring another
  browser login."* It gives no number.
- The 7, 30, 60 and 90 day figures in search results are the validity
  choices for **workspace Codex access tokens**
  (`login/src/auth/personal_access_token.rs`), a separate credential type.
  They say nothing about the device login.
- `help.openai.com/en/articles/11369540` returned a Cloudflare challenge and
  was not read.

## Consequences for N4

1. **Log in once.** Later runs renew the binding by using it.
2. **Re-login cadence is unknown until measured.** S10 (an active-path startup
   at least 24 hours after login) observes the first refresh. If a binding
   left idle expires quickly, a scheduled startup run (four methods, no model
   request) would keep it renewed. That is a decision after S10, not before.
3. **A kill during a save can cost the binding.** Truncate-then-write is not
   atomic. A vendor process killed between the two, by the lane's deadline or
   by power loss, can leave `auth.json` empty or partial. If the server had
   already rotated the token, the old one is spent too. The next run refuses
   and maintenance logs in again. The window is the length of one small write.
   The vendor's save cannot be changed from here, so it is recorded as a limit.

## Could not verify

- The server-side lifetime of the refresh token, and whether idle bindings are
  revoked separately.
- The contents of the help-centre article above.
- Whether the ~10-day access-token `exp` reported in openai/codex#44579 is
  typical. It is one user's observation.
