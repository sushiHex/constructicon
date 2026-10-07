# M8 N5: `account/read` recovery, credential-free

Status: design, independently reviewed once (Codex `gpt-6-sol`, job
`job_63e271332db7`) and amended; see [Review disposition](#review-disposition).
Credential-free: every host is a fake behind the relay with a throwaway CA;
nothing here contacts OpenAI, qualifies a destination or makes the provider
available.
Scope: the Stage 0 item of
[M8-N5-state-review.md](M8-N5-state-review.md) line 85: "Its recovery path is
tested credential-free: a 401, then refresh, then a clean or refused reading.
Store, mode, configuration and egress restrictions hold throughout."
Authority: [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md),
unchanged; no production code changes.

Pinned source: `openai/codex` tag `rust-v0.160.1`, commit `d27764b8`. Paths are
relative to `codex-rs/`.

## Findings at the pin

1. **Discovery races the adapter.** `initialize` spawns the server's own
   account discovery, recovery included, and a successful one sends
   `account/updated` (`app-server/src/message_processor.rs:937-951`,
   `request_processors/account_processor/workspace_routing.rs:131-155`). The
   adapter's `account/read` may share that fetch, reuse its success, or start
   its own discovery: a failed discovery is not cached as routing
   (`workspace_routing.rs:225-328`, `:357-374`). A test must judge the fake's
   ordered request log, not only the reply.
2. **The check.** `GET https://chatgpt.com/backend-api/wham/accounts/check`
   with `Authorization: Bearer <tokens.access_token>` and
   `ChatGPT-Account-ID: <tokens.account_id>`. Discovery is skipped without
   `tokens.account_id`, and the bearer is sent only with `last_refresh`.
3. **One discovery's recovery** (`login/src/auth/manager.rs:1976-2017`): check
   401, reload `auth.json` from disk, check 401 again, refresh, check once more.
   A later discovery can run it again, refresh included.
4. **The refresh.** `POST https://auth.openai.com/oauth/token` with JSON
   `{"client_id", "grant_type": "refresh_token", "refresh_token"}`
   (`manager.rs:212-214`). Returned fields are optional: only those supplied
   replace the old tokens.
5. **The rewrite is in place:** truncate, write, flush, mode 0600, no rename
   and no `fsync` (`login/src/auth/storage.rs:206-223`). The bound
   credential's inode survives; `last_refresh` is always set.
6. **The account must not change.** The parsed user id and the top-level
   `tokens.account_id` are compared after the refresh (`change_state.rs:15-30`,
   `workspace_routing.rs:303-318`). A change refuses the reading as "account
   changed during workspace routing discovery", after the new tokens are
   already persisted: the refusal does not roll them back.
7. **Refusals.** An issuer refusal (401, `invalid_grant`) is permanent and
   cached. Depending on timing the adapter's reading is then the unauthorized
   JSON-RPC error or `account: null`; a check still 401 after a good refresh
   is the unauthorized error. The adapter refuses all of them.
8. **The rate-limits readback** sends `GET .../wham/usage` and
   `GET .../wham/rate-limit-reset-credits`. A 401 there is not recovered, but
   the handler's `auth()` calls can refresh proactively near the access
   token's expiry (`account_processor.rs:1119-1157`, `:1194-1202`). The
   minimal clean usage body is `{"plan_type": "pro"}`.
9. **Hosts.** Under the production configuration the client contacts only
   `chatgpt.com` and `auth.openai.com`; the background workers were not
   enumerated, so the relay record decides.

## Design

The production startup lane, `codex_lane.run_startup`, drives the real binary
with production's configuration, command, launcher, bridge and eight-connection
bound, unchanged: the adapter's four authorized methods, its verdict, the
relay, and custody's terminal check. Only the destinations are fakes.

- **One fake at production's ports.** A scripted HTTPS server on
  `127.0.0.1:443` serves both `chatgpt.com` and `auth.openai.com`, choosing its
  certificate by SNI from the trust fixture's throwaway CA, which gains a
  `chatgpt.com` leaf beside its `auth.openai.com` one
  (`scripts/ci/build_m8_trust_fixture.py`). The policy pins both hosts at 443
  to the controlled loopback address, so the client's default URLs reach it and
  no shim or extra configuration is needed. One server keeps one ordered log
  across both hosts.
- **Binding 443.** The test runs as the non-root service user, so its CI step
  lowers `net.ipv4.ip_unprivileged_port_start` to 443 for that step only, on
  the disposable runner, and restores it. The zone is in its own network
  namespace and unaffected.
- **The credential.** The store's `auth.json` is swapped for a fixture with an
  unsigned id_token (`chatgpt_user_id`, plan `pro`), `tokens.account_id`, a
  recent `last_refresh`, and an access token expiring far in the future; every
  token the issuer returns expires far in the future too. The original bytes
  are restored after.
- **No token in evidence or in a failure message.** The fake classifies each
  bearer and refresh token as old, new or unknown and logs only the method,
  host, path and class.

The fake answers the check by bearer class (old: 401; new: one account,
`workspace_backend_origin: "https://chatgpt.com"`,
`account_routing_override: "NO_CONSTRAINT"`), usage with `{"plan_type": "pro"}`
and reset credits with 404. The issuer's answer and the check's answer to the
new bearer are the case.

| Case | Issuer | Check, new bearer | Expected |
|---|---|---|---|
| clean | new tokens, same account | the account | all four methods, no fault, the gate completed at `pro`, a spend readback, `refresh: measured`; the log: two old-bearer checks, one POST carrying the old refresh token, then new-bearer checks, usage and reset credits; `auth.json` the same inode, 0600, holding the new tokens |
| refused refresh | 401 `invalid_grant` | (unreached) | stops at `account/read`: the unauthorized fault or the no-account fault, the gate incomplete, no readback; `auth.json` byte-identical |
| still unauthorized | new tokens | 401 | stops at `account/read` with the unauthorized fault; the new tokens persisted in place |
| account changed | new tokens for another user | the account | stops at `account/read` refused as an account change; the new tokens persisted in place |
| unsealed backend | new tokens | origin `https://elsewhere.invalid`, override valid | stops at `account/read` with exactly `UNSEALED_BACKEND_FAULT` |

Every case also asserts: no relay denial; only the two sealed destinations
accepted; every TLS session complete, without an alert; the store directory
holding only `auth.json`; the credential one regular 0600 file on the same
inode; the zone's configuration production's. Exact request counts are
measured on the first real-binary run and then pinned, as the native tool
inventory's were.

### What could pass vacuously, and the guard

| Hazard | Guard |
|---|---|
| a cached reply judged without a request | the ordered request log is asserted per case |
| no `tokens.account_id`, so no check | the clean case requires the checks |
| the old bearer accepted after the reload, so no refresh | the fake 401s it every time; one POST is required |
| a proactive refresh from either token's expiry | far expiry on the old and the new access token |
| an empty refresh moving only `last_refresh` | the clean case requires the new tokens in the file |
| a TLS failure reading as a refusal | the exact fault per case, and no alerts |
| an account switch reading as a recovery refusal | its own case, its own fault |
| a routing control refused before `routing_faults` | a complete, valid check response with an override |

## Placement

The foundation lane's N4 bridge step, beside the device-login trust test that
already runs the trust runtime and a fake `auth.openai.com`.

## Not in scope

- A transient refresh failure (5xx, malformed JSON) retries on every later
  reading; it is refused either way.
- Proactive refresh at token expiry, which the turn's own path takes; Stage 3.

## Corrections found on the way

- `codex_lane.py:130` cites `manager.rs:197` for the refresh URL; at the pin it
  is `:212`.
- `codex_protocol.py:303` cites `common.rs:1234-1238` for
  `account/rateLimits/read`; at the pin it is `:1309-1313`, with optional params.

## Review disposition

One Codex pass (`gpt-6-sol`, `xhigh`, job `job_63e271332db7`) on the draft.

Adopted:
- **The composition changed what it proved.** The draft's exec shim and
  `chatgpt_base_url` line moved the client off production's URLs, and the
  research's sixteen-connection policy widened the egress bound. One fake at
  production's ports keeps the configuration, command and bound production's,
  and lets the lane's own `refresh: measured` judgement count.
- **Discovery is per reading, not per startup:** the adapter's reading races
  or repeats it, and a permanent refusal can surface as `account: null`.
  Findings 1, 3 and 7 now say so, and the refused case accepts either fault.
- **Per-case verdicts in `run_startup`'s terms,** and the cross-host order,
  which one server's log gives.
- **An account-change case,** with the tokens persisted before the refusal.
- **The routing control must be a complete, valid check response,** or the
  vendor refuses before `routing_faults` sees the origin.
- **Far expiry for the new access token too.**
- **No token in evidence or in assertion messages.**

Recorded as a design choice: "mode" and "configuration" are asserted as
invariants every case holds, not with new adverse controls. The credential's
mode and the read-only sealed configuration already have adverse controls in
the N3a and N4 lanes (`test_operator_store_containment.py`,
`test_operator_store_persistence.py`).
