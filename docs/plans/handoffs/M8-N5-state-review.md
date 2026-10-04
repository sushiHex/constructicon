# M8 N5 state review: the first subscription turns

Status: pre-code design for owner decision. Nothing here authorizes a model
call. It builds on N4 at `88effe1`:
- the binding passed every startup control on the private host, and g3 is active;
- refresh is unmeasured ([#77](https://github.com/sushiHex/constructicon/issues/77)).

A Codex (`gpt-6-astra`) review of the first draft returned "rework". Its
findings are adopted below. Vendor facts are now read from the pinned source
(`openai/codex` at `rust-v0.153.4`), not inferred.

## Authority

N5 (`M8-live-executors-rev3.md`, "N5"):
- one bounded READ lane and a separately authorized WRITE/capture/gate lane, through the owned boundaries, on the real launcher, driver, worker and leases;
- no unqualified production provider published and no conformance hash invented;
- limits, unavailable telemetry and partial output reported truthfully.

The owner's terms are on #78:
- [2026-09-24](https://github.com/sushiHex/constructicon/issues/78#issuecomment-5807849388): the default catalog model at its lowest listed effort; one READ turn, then one WRITE turn, each in its own lane, with at most one retry after a diagnosed local failure; harmless repository-local fixtures; stop conditions.
- [2026-10-01](https://github.com/sushiHex/constructicon/issues/78#issuecomment-5945414633): `operator_authorized` overage bounded by the account's own settings, carry-over authorized, and no turn started while the account reports its spend control reached.

The later decision replaces three rows of the earlier one: the purchased-credit
bound, the $0 ceiling, and the stop on any change from the overage baseline.

## Pinned facts

1. **The answer is in `turn/completed`.** At the pin, `emit_turn_completed_with_status` puts the turn's last agent message in `turn.items` with `itemsView: "summary"`. A turn with no message carries none, with `"notLoaded"` (`app-server/src/bespoke_event_handling.rs:1392-1416`).
   - An agent message is `{type: "agentMessage", id, text, phase?, …}` (`app-server-protocol/src/protocol/v2/item.rs:250-261`).
   - The pinned `Turn` has no `output`, `model` or `usage` (`v2/thread_data.rs:366-386`). Today's decoder reads exactly those three (`codex_protocol.py:1266-1269`), so a real turn would decode as a success with no output. The scripted fakes manufacture the three fields (`tests/substrate/test_codex_protocol.py:163`).
2. **Usage is `thread/tokenUsage/updated`** (`v2/common.rs:1867`), carrying `{threadId, turnId, tokenUsage: {total, last, modelContextWindow}}` (`v2/thread.rs:1834-1880`).
   - `total` is the thread's running sum. Each conversation opens one thread for one turn, so `total` is the turn's usage.
   - The evidence allowlist admits only `turn/*`, `error`, `warning` and `configWarning` (`codex_protocol.py:568-569`), so today this notification is excluded.
3. **A served model is emitted only on a reroute**, `model/rerouted` (`common.rs:1918`). Otherwise the served model is unknown, never the requested one.
4. **Effort is not enforced.** The grants require an explicit listed effort (`native_operator.py:193-199`), but neither the turn request (`codex_protocol.py:467-488`) nor the sealed configuration (`codex_lane.py:572-584`) carries one. The pinned catalog lists `low`, `medium`, `high` and `xhigh` for `gpt-5.5`, with default `medium` (catalog `d7136a41…`).
5. **No token ceiling and no request count are enforced.** Constructicon enforces one `turn/start` per conversation, a wall-clock deadline, cumulative input bytes and, for WRITE, eight bounded callbacks. The backend may make several model requests per turn (retries, tool continuations), and no evidence counts them.
6. **Relay denials do not refuse a provider turn.** The handle returns the process result without judging the relay's counters (`codex.py:1703`). The lane's `check_evidence` does require `denied == {}`.

## Design

**Stage 0: credential-free, one PR.**
- **Decoder.** Decode the pinned shape, correlated to this thread and turn:
  - the answer is the `agentMessage` text in this turn's `turn/completed` items;
  - usage is the last `thread/tokenUsage/updated` naming this thread and turn, admitted to the allowlist with bounded fields;
  - the served model is reported only from a `model/rerouted` for this turn.
- **Deferral.** Notifications that arrive before the `turn/start` reply names the turn are deferred with it, not excluded (`codex.py:568`).
- **Fakes.** Rebuild the fakes to the pinned shape, with assertion-killed mutants:
  - the old fields restored;
  - another turn's message or usage taken;
  - the requested model inferred as served;
  - an early notification lost.
- **Effort.** Seal `model_reasoning_effort = "low"`, and have the provider refuse grants whose effort differs from the configuration's, as it already does for the model.
- **Evidence check.** `check_evidence` compares the recorded adapter, protocol, configuration and runtime identities with the installed ones, not only their presence.
- **What it changes.** `PROTOCOL_REVISION`, `ADAPTER_REVISION` and the configuration digest change. The store and login do not.

**Stage 1: requalify for the new configuration (N4 commands, no model call).**
- Replace the controller (LR8 or R17 to R19), then verify the launch set and drift.
- S1 into a fresh session directory, which produces the new `config.toml`. S1 never touches the store.
- Under maintenance, S4 and S6a, then publish and activate the next generation (g4), then the active startup.
- The old generation must refuse.
- Old evidence stays historical; it qualified the old configuration only.

**Stage 2: the one READ turn.**
- `codex_lane turn` runs under active custody with every lane guard:
  - binding checks before spawn and after quiescence;
  - the sealed model and effort, READ grants, no callbacks;
  - both readback gates, all account, provider and settings faults, correlation, and the EOF audit;
  - the sealed relay policy, where any denial is a fault;
  - one absolute deadline whose cancellation joins teardown before custody is released.
- It sends one fixed task kept in code, a harmless instruction that needs no repository data, and records its digest.
- The evidence records:
  - the decoded answer's presence and length, never its text if it could carry account data;
  - usage, and the served model or "unknown";
  - readbacks before and after;
  - relay counts and process facts;
  - the identities;
  - attempt accounting: intent recorded before dispatch, then "not dispatched", "possibly dispatched" or "completed".
- The backend request count is recorded as unknown.
- This turn **is** the one authorized READ. Its coverage is the lane, not the provider's leases; the record says so.

**Stage 3: WRITE, designed separately.** The provider's `acquire` refuses while
unavailability reasons stand (`codex.py:2021`), and clearing reasons that have
not been earned is not allowed. WRITE needs either every prerequisite earned,
or a narrow qualification-only entry that shares the real acquisition,
materialization and cleanup without becoming a production provider. Either is
its own reviewed design, after Stage 2's facts. It also needs the provider to
judge relay denials (fact 6), and a credential-free WRITE, capture and gate
smoke against the host's runtime Python.

**Refusal and retry.** Each of these refuses and is recorded:
- an account or provider notice other than a plan-checked `account/rateLimits/updated`;
- a mode or plan change;
- an unreadable readback;
- the spend control reached before `turn/start`;
- a relay denial;
- any other fault.

Credit changes and a spend control reached after dispatch are authorized
carry-over, not refusals. Only a diagnosed local failure with the turn **not
dispatched** may be retried once. A possibly dispatched turn is never retried
automatically, and a wrong answer is not a local failure.

## Owner decisions

1. **The merged N5 terms.** Confirm:
   - `gpt-5.5` at `low`;
   - one READ turn (Stage 2), then a separately designed and authorized WRITE turn;
   - harmless repository-local fixtures;
   - the 2026-10-01 overage bound in place of the 2026-09-24 credit rows;
   - the budget as Constructicon can enforce it: one turn, a 600 s wall clock, and no token ceiling or request count.
2. **The READ turn's coverage.** It runs through the lane's guards, not the provider's leases. Accept that as the READ deliverable, or require the provider path, which needs Stage 3's acquisition design first and adds no READ attempt?
3. **Refresh unmeasured.** May N5 run while `vendor_conformance_qualified` is false? The READ turn may itself trigger and record the refresh N4 could not observe.
