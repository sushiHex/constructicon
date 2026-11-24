# M8 N5 state review: the first subscription turns

Status: design, decided by the owner on 2026-10-05, including the budget.
Nothing here authorizes a model call or a host action; each stage runs under
its own authorization. It builds on N4 at `88effe1`:
- the binding passed every startup control on the private host, and g3 is active;
- refresh is unmeasured ([#77](https://github.com/sushiHex/constructicon/issues/77)).

Codex (`gpt-6-astra`) reviewed two drafts and the owner's decisions. All of
its findings are adopted. Vendor facts are read from the pinned source; where
only an audit stands behind a claim, the claim says so.

## Authority and decisions

N5 (`M8-live-executors-rev3.md`, "N5"):
- one bounded READ lane and a separately authorized WRITE/capture/gate lane, qualified through the real launcher, driver, worker **and leases**;
- no unqualified production provider published and no conformance hash invented;
- limits, unavailable telemetry and partial output reported truthfully.

The owner's terms:
- [#78, 2026-09-24](https://github.com/sushiHex/constructicon/issues/78#issuecomment-5807849388): one READ turn, then one WRITE turn, at most one retry after a diagnosed local failure; harmless repository-local fixtures.
- [#78, 2026-10-01](https://github.com/sushiHex/constructicon/issues/78#issuecomment-5945414633): `operator_authorized` overage bounded by the account's own settings, carry-over authorized, no turn started while the account reports its spend control reached.
- 2026-10-04: "the latest installed and available", updated "as seamless as possible", for the client and the model.

Decided on 2026-10-05 ([#78](https://github.com/sushiHex/constructicon/issues/78)):
1. **`account/updated` is admitted on an exact match only** (Stage 0).
2. **An unsealed backend stops the session.** A new destination is reviewed and sealed separately, never added from an account reply at runtime.
3. **The model is the newest listed version of the chosen family, at its lowest listed effort.** This is a standing rule, so a pin bump moves it. The family is `sol`, which is `gpt-6.1-sol` at `low` today.
4. **The READ turn runs through the real lease path,** not a lane. The qualification acquisition comes before it.
5. **Refresh is measured before the READ turn.** A turn that triggers refresh cannot justify its own missing prerequisite.

6. **The budget is a fixed attempt budget.** M8 asks for a "fixed request/token budget". Constructicon enforces dispatch, time, byte and callback limits, and cannot enforce a token or request ceiling (fact 8). After Codex's recommendation, the owner accepted these terms:

   > For N5 I accept the specified dispatch, deadline, byte and callback limits as the fixed attempt budget. Token usage is observational; backend request count is unknown. No hard token, backend-request or finite monetary ceiling is requested or claimed. My October 1 overage and carry-over decision remains applicable. READ and WRITE require their separate stage authorizations.

   | Item | Bound |
   |---|---|
   | Dispatches | One READ `turn/start`, then one separately authorized WRITE `turn/start` |
   | Retry | At most one more attempt across N5, only after a diagnosed local failure known not to have dispatched. A turn that may have dispatched uses up its stage's attempt |
   | Time | READ 120 s; WRITE 300 s, shared by the exchange and its callbacks. These are proposed limits, not measured run times |
   | Bytes and tools | The sealed cumulative input limit (1 MiB by default, confirmed from the recorded value); eight bounded WRITE callbacks; none for READ |
   | Tokens | The vendor's usage recorded when it can be attributed to the turn, otherwise "unknown". Never zero, never "within budget" |
   | Backend requests | Unknown |

   M8's "stop for a different operator decision" applies to a requested hard spending bound that cannot be enforced. None is requested.

## The upgrade routine

Every vendor upgrade takes the same short path.

1. **One pin record.** Version, asset URL and sha256, and catalog commit and sha256 live in one reviewed file that the workflow, the installer and the lane all read.
2. **A bump tool.** It finds the newest stable release, checks the asset against the release's published `SHA256SUMS`, hashes the catalog at the release's commit, rewrites the pin record, and opens a PR.
3. **The real-binary proofs are the gate.** A failing proof names what changed. A surface the proofs do not exercise is added to them before it is relied on.
4. **Model and effort from the catalog,** per decision 3.
5. **One host update session.** The store-keeping launch replacement (`M8-N4-launch-replacement.md`), a controller check, then startup requalification into the next generation. There is no re-login unless the vendor forces one.

## Facts at `rust-v0.160.0`

The newest release is `rust-v0.160.0` (2026-10-01). Its tarball sha256 is
`4fcc47ab…6b71`, matching its published `SHA256SUMS`. Its catalog is at
`a956835d`, sha256 `fd219bd9…920b`. Items marked "audit" come from the
0.153.4 to 0.160.0 audit and are verified in Stage 0.

1. **Startup sends `account/updated {authMode, planType}`** on `initialize` (audit: `message_processor.rs:816-817`). Today every `account/updated` refuses (`codex_protocol.py:752-753`).
2. **`account/read` calls `{chatgpt_base_url}/wham/accounts/check`** (audit: `workspace_routing.rs:290-325`).
   - A 401 there triggers recovery, which can refresh the token, so the readback can no longer be assumed never to refresh (`codex_protocol.py:11-15, :291`).
   - The check may name another backend origin for some workspaces (audit: `:427-468`).
3. **The answer is in `turn/completed`:** the turn's last `agentMessage` text, in `turn.items` with `itemsView: "summary"` (`bespoke_event_handling.rs:1321-1347`; `v2/item.rs:252-263`). Today's decoder reads `turn.output`, `model` and `usage`, which the pin never sends (`codex_protocol.py:1266-1269`), so a real turn would decode as a success with no output.
4. **Usage is `thread/tokenUsage/updated`** (`{threadId, turnId, tokenUsage: {total, last, …}}`), excluded today by the evidence allowlist (`codex_protocol.py:568-569`). Whether `total` is exactly the turn's usage is verified, not assumed.
5. **A served model is emitted only on `model/rerouted`.** Otherwise it is unknown.
6. **Effort is not enforced today**, though `model_reasoning_effort` exists at the pin.
7. **The newest models per family:** `gpt-6.1-sol` (the default), `gpt-6-astra`, `gpt-6-luna` and `gpt-5.6-terra`, each with `low` as its lowest effort.
8. **No token ceiling and no request count.** The backend may make several requests per turn: retries (audit: 5 stream, 4 request) and tool continuations.
9. **Relay denials do not refuse a provider turn.** The provider does not judge the relay's counters (`codex.py:1703`); the lane does (`codex_lane.py:430`).
10. **The package adds a voice host** (audit: `codex-resources/voice/`). `webpki-roots` is a build dependency, but which roots the HTTP clients actually trust is unproved. Both need real-binary controls.

## Design

**Stage 0: credential-free, one PR.**
- **The routine,** with the pin moved to 0.160.0, after the audit's claims are verified at the pin.
- **`account/updated`.** Admitted only as exactly `{authMode: "chatgpt", planType: <the sealed plan>}`, both strings, with no `id`, no reply or error fields, and no null, extra or missing keys.
  - A notice before the first reading is held and must agree with that reading before anything proceeds. Under qualification's two-plan set, it must agree with the one literal the reading establishes.
  - Identical repeats pass anywhere, including mid-turn and in the drain. Any contradiction latches a refusal that a later match cannot clear.
  - `account_request_faults` keeps refusing id-bearing account messages.
- **`account/read`.** Its recovery path is tested credential-free: a 401, then refresh, then a clean or refused reading. Store, mode, configuration and egress restrictions hold throughout.
- **Decoder.**
  - The answer, usage and served model come from the pinned events, correlated to this thread and turn. Notifications before the `turn/start` reply are deferred with it.
  - **A READ answer is accepted only as non-empty `agentMessage` text.** A timeout keeps the partial text as an observation, never as an accepted result.
  - Fakes are rebuilt to the pinned shape. Assertion-killed mutants cover: the old fields; another turn's evidence; an inferred served model; a lost early notification; an empty answer accepted.
- **Model and effort** are sealed from the catalog, and the provider refuses grants whose model or effort differs from the configuration's.
- **Relay denials** are judged in the shared provider outcome path, so a successful answer cannot mask one.
- **Evidence check.** `check_evidence` compares the recorded adapter, protocol, configuration and runtime identities with the installed ones.
- **Real-binary controls** for the trust roots the client uses and for the voice host never running.

**Stage 1: the qualification acquisition, credential-free, one PR.**
- A narrow entry that runs the real acquire, record, enroll, materialize, cancel, close and reconcile implementation.
- It never makes the provider available and clears no unearned reason.
- It needs the bounded qualification authorization to run.
- Deterministic fault tests: lease recording, cancellation, loss of ownership, joined cleanup and recovery.

**Stage 2: the host update session (no model call).**
- The store-keeping launch replacement and the controller check at the new commit.
- S1 into a fresh session directory.
- Under maintenance, S4 and S6a, then g4, the active startup, and the old generation refusing.
- Then refresh: a no-model active startup on each authorized session until one measures it (an `auth.openai.com` connection, a changed credential, a clean readback). The token's expiry is unobserved, so the date is unknown.

**Stage 3: the one READ turn,** through Stage 1's acquisition path, with a fixed harmless task. Each invocation takes a fresh acquisition and records its own lease (`lease_id_for`: one per run, invocation and binding); a closed acquisition is never reused.
- The evidence records the accepted answer's length, usage, the served model or "unknown", the readbacks, relay counts, process facts and identities.
- Attempt accounting: intent recorded before dispatch, then "not dispatched", "possibly dispatched" or "completed".
- Usage is recorded when it can be attributed to the turn, otherwise "unknown". The backend request count is unknown. Both follow decision 6.

**Stage 4: the WRITE turn,** through the same acquisition path with its own fresh acquisition and lease, and with the real worker, capture and gate. Before it, a credential-free WRITE, capture and gate smoke runs against the host's runtime Python.

**Refusal and retry.** Each of these refuses and is recorded:
- an account or provider notice outside the two admitted forms (the plan-checked `account/rateLimits/updated` and the exact `account/updated`);
- a mode or plan change;
- an unreadable readback;
- the spend control reached before `turn/start`;
- a relay denial;
- any other fault.

Credit changes and a spend control reached after dispatch are authorized
carry-over. Only a diagnosed local failure with the turn not dispatched may be
retried once. A possibly dispatched turn is never retried automatically, and a
wrong answer is not a local failure.
