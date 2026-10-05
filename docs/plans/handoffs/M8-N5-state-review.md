# M8 N5 state review: the first subscription turns

Status: pre-code design for owner decision. Nothing here authorizes a model
call. It builds on N4 at `88effe1`:
- the binding passed every startup control on the private host, and g3 is active;
- refresh is unmeasured ([#77](https://github.com/sushiHex/constructicon/issues/77)).

A Codex (`gpt-6-astra`) review of the first draft returned "rework". Its
findings are adopted below. Vendor facts are read from the pinned source,
never inferred.

## Authority

N5 (`M8-live-executors-rev3.md`, "N5"):
- one bounded READ lane and a separately authorized WRITE/capture/gate lane, through the owned boundaries, on the real launcher, driver, worker and leases;
- no unqualified production provider published and no conformance hash invented;
- limits, unavailable telemetry and partial output reported truthfully.

The owner's terms:
- [#78, 2026-09-24](https://github.com/sushiHex/constructicon/issues/78#issuecomment-5807849388): the default catalog model at its lowest listed effort; one READ turn, then one WRITE turn, each in its own lane, with at most one retry after a diagnosed local failure; harmless repository-local fixtures; stop conditions.
- [#78, 2026-10-01](https://github.com/sushiHex/constructicon/issues/78#issuecomment-5945414633): `operator_authorized` overage bounded by the account's own settings, carry-over authorized, no turn started while the account reports its spend control reached. This replaces the 2026-09-24 purchased-credit bound, $0 ceiling and baseline stop.
- The working session, 2026-10-04: "we typically always want the latest installed and available", and "each version update should be as seamless as possible". This covers the vendor client as well as the model.

## The upgrade routine

Every vendor upgrade takes the same short path, so "latest" never means a migration.

1. **One pin record.** Version, release asset URL and sha256, and catalog commit and sha256 live in one reviewed file that the workflow, the installer and the lane all read. Today they are spread across `m8-containment.yml`, the docs and `PREPARE_MODEL`.
2. **A bump tool.** It finds the newest stable release, checks the asset against the release's published `codex-package_SHA256SUMS`, hashes the catalog at the release's commit, rewrites the pin record, and opens a PR.
3. **The real-binary proofs are the gate.** The containment, mediation and startup lanes run the pinned binary against scripted peers, so on a bump PR they are the compatibility check. A failing proof names what changed. A surface the proofs do not exercise is added to them before it is relied on.
4. **No model literal.** The sealed model is the newest listed version of the owner's chosen family in the pinned catalog. Its effort is the lowest listed one. A bump moves both.
5. **One host update session.** The store-keeping launch replacement (`M8-N4-launch-replacement.md`), a controller check, then startup requalification into the next generation. These are existing commands, with no re-login unless the vendor forces one.

## Facts at the newest release, `rust-v0.160.0`

The newest release is `rust-v0.160.0` (2026-10-01). Its tarball sha256 is
`4fcc47ab…6b71`, matching its published `SHA256SUMS`. Its catalog is at
`a956835d`, sha256 `fd219bd9…920b`. Where 0.160.0 differs from the current
pin, `0.153.4`, the item says so; everything else is unchanged.

1. **Startup now sends `account/updated` (new, and blocking).** Every authenticated connection now receives `account/updated {authMode, planType}` on `initialize` (`message_processor.rs:816-817`; `account_processor.rs:224-233`). Today every `account/updated` refuses (`codex_protocol.py:752-753`), so every startup and turn would refuse.
2. **`account/read` now calls the network (new).** It calls `{chatgpt_base_url}/wham/accounts/check`. A 401 there triggers recovery, which can refresh the token (`account_processor/workspace_routing.rs:290-325`), and a failed check makes the read an error. The destination is `chatgpt.com`. The check may also name a different backend origin for some workspaces (`:427-468`); for this account that is unverified.
3. **The answer is in `turn/completed`.** The turn's last `agentMessage` (`{type: "agentMessage", id, text, …}`) is in `turn.items`, with `itemsView: "summary"`; a turn with no message carries none (`bespoke_event_handling.rs:1321-1347`; `v2/item.rs:252-263`).
   - The `Turn` has no `output`, `model` or `usage`.
   - Today's decoder reads exactly those three (`codex_protocol.py:1266-1269`), so a real turn would decode as a success with no output. The fakes manufacture the three fields.
4. **Usage is `thread/tokenUsage/updated`.** It carries `{threadId, turnId, tokenUsage: {total, last, modelContextWindow}}`. With one turn per thread, `total` is the turn's usage. The evidence allowlist excludes it today (`codex_protocol.py:568-569`).
5. **A served model is emitted only on `model/rerouted`.** Otherwise it is unknown, never the requested one.
6. **Effort is not enforced today.** Neither the turn request nor the sealed configuration carries it, though `model_reasoning_effort` exists at the pin.
7. **The catalog's newest models per family.** `gpt-6.1-sol` (the default), `gpt-6-astra`, `gpt-6-luna` and `gpt-5.6-terra`. Each lists `low` as its lowest effort.
8. **No token ceiling and no request count.** Constructicon enforces one `turn/start`, a wall-clock deadline, input bytes and, for WRITE, eight callbacks. The backend may make several requests per turn (5 stream and 4 request retries, tool continuations), and nothing counts them.
9. **Relay denials do not refuse a provider turn.** The handle does not judge the relay's counters (`codex.py:1703`); the lane's evidence check does.
10. **Unchanged from 0.153.4.** Device login, the refresh rules, the in-place `auth.json` save, `CODEX_CA_CERTIFICATE`, proxy handling, endpoints, the sealed config keys and the rate-limit readback. `webpki-roots` is in the build at both tags, so the trust claim's open question is answered: compiled-in roots exist alongside the store.
11. **The package adds a voice host** (`codex-resources/voice/`). The vendor-tree digest changes. That it never runs without realtime methods is unverified.

## Design

**Stage 0: credential-free, one PR.**
- **Routine.** The pin record and bump tool, moved to `rust-v0.160.0`.
- **`account/updated`.** Admitted only when its `authMode` is `chatgpt` and its plan is the accepted one. That restates the readings, so it is not a mode change. Anything else still refuses (decision 1).
- **Decoder.** Decode the pinned turn, correlated to this thread and turn:
  - the answer from `turn/completed` items;
  - usage from this turn's `thread/tokenUsage/updated`;
  - the served model only from `model/rerouted`;
  - notifications that arrive before the `turn/start` reply are deferred with it.
  
  The fakes are rebuilt to the pinned shape. Assertion-killed mutants cover: the old fields restored; another turn's evidence taken; the served model inferred; an early notification lost.
- **Effort and model.** Seal the effort, derived from the catalog, and have the provider refuse grants whose model or effort differs from the configuration's.
- **Evidence check.** `check_evidence` compares the recorded adapter, protocol, configuration and runtime identities with the installed ones.

**Stage 1: the first host update session (no model call).**
- The store-keeping launch replacement at the new commit, and the controller check.
- S1 into a fresh session directory, for the new configuration.
- Under maintenance, S4 and S6a, then publish and activate g4, then the active startup, with the old generation refusing.
- The `account/read` network check is observed here first. A backend origin other than `chatgpt.com` is a relay denial, so the session stops (decision 2).

**Stage 2: the one READ turn.**
- `codex_lane turn` runs under active custody with every lane guard:
  - binding checks before spawn and after quiescence;
  - the sealed model and effort, READ grants, no callbacks;
  - both readback gates, all account, provider and settings faults, correlation, and the EOF audit;
  - the sealed relay, where any denial is a fault;
  - one absolute deadline whose cancellation joins teardown.
- It sends one fixed, harmless task kept in code, and records its digest.
- The evidence records:
  - whether an answer is present, and its length;
  - usage, and the served model or "unknown";
  - readbacks, relay counts and process facts;
  - the identities;
  - attempt accounting: intent recorded before dispatch, then "not dispatched", "possibly dispatched" or "completed".
- The backend request count is recorded as unknown.
- This is the one authorized READ, and its coverage is the lane's.

**Stage 3: WRITE, designed separately.** The provider refuses to acquire while
unavailability reasons stand (`codex.py:2021`), and clearing unearned reasons
is not allowed. WRITE needs either every prerequisite earned, or a narrow
qualification-only entry that shares the real acquisition and cleanup without
becoming a production provider. It also needs relay denials judged (fact 9)
and a WRITE, capture and gate smoke against the host's runtime Python.

**Refusal and retry.** Each of these refuses and is recorded:
- an account or provider notice other than the plan-checked `account/rateLimits/updated` and the matching `account/updated`;
- a mode or plan change;
- an unreadable readback;
- the spend control reached before `turn/start`;
- a relay denial;
- any other fault.

Credit changes and a spend control reached after dispatch are authorized
carry-over. Only a diagnosed local failure with the turn not dispatched may be
retried once. A possibly dispatched turn is never retried automatically, and a
wrong answer is not a local failure.

## Owner decisions

1. **`account/updated` at 0.160.0.** Admit it only when it restates the readings (`authMode: chatgpt`, the accepted plan), and refuse it otherwise? This is ADR 0021's "observed mode change" read as a change, not as any notice.
2. **A routed backend origin.** If `accounts/check` names a backend other than `chatgpt.com`, refuse it as a relay denial (recommended), or review it as a new sealed destination?
3. **The family.** The model is derived from the catalog. Which family: `sol` (now `gpt-6.1-sol`, the catalog default), `astra` (`gpt-6-astra`), or another? The effort is the lowest listed, `low`.
4. **The READ turn's coverage.** It runs through the lane's guards, not the provider's leases. Accept that as the READ deliverable, or require the provider path, which needs Stage 3's design first?
5. **Refresh unmeasured.** May N5 run while `vendor_conformance_qualified` is false? Stage 1's `account/read` and the READ turn may themselves record a refresh.
