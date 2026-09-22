# N5 spend-bound research: Codex (ChatGPT plan) and Claude Code (Claude plan)

Research input for issue #78 (N5), not authorization, a spend guarantee or
qualification. Retrieved 2026-09-22. Vendor pages were fetched with `curl` and
tag stripping; the text copies were working files and are not committed. No
WebFetch, no login, no model call. Quotes are verbatim from those copies.
Several OpenAI pages said "Updated: 3 hours ago", "yesterday" or "2 hours ago"
on the day they were fetched, so treat every vendor quote as correct on that
date only. Codex source is a sparse clone of tag `rust-v0.153.4`. The tag
object is `042fb41b…`, and `git rev-parse HEAD` returned
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`, the same commit the repository
cites (`docs/adr/0020-native-harnesses-mediate-contained-tools.md:59`). Paths
marked `codex-rs/...` are in that checkout.

**Second reading.** A second reader re-fetched the pages behind the most
load-bearing quotes with `curl` the same day and matched them verbatim: the
Claude Pro/Max "Once disabled…" answer and credit-scope sentence; the Claude
Team disable and overshoot passages; the ChatGPT Enterprise/Edu default and
"limit to 0" passages; the Business "feature is blocked" passage and its
seat-limit default and recharge cap; the personal-credits reload cap,
negative-balance and add-credits sentences; and both in-turn continuation
sentences. All reproduced. One quote carried a tag-stripping artifact and was
corrected ("Cap spend:" in 2b). From the pinned git objects the second reader
also re-read the Codex `Turn`, the `account/rateLimits/read` registration and
its response and snapshot types in 1d; and from this repository the adapter
lines, issue #78's text and the rev 3, preflight, implementation-record and
test citations. The other `codex-rs` citations were not independently re-read.

Mainframe: `mcp__mainframe__search` was available and was searched first. It
had no vendor overage-policy research. Its useful hit was this repository's
`docs/plans/handoffs/M8-native-account-interface-preflight.md` (account method
inventory, lines 76-80), and the rest of this report builds on that.

## Constraint being answered

Issue #78 (N5) says: "Requires explicit operator authorization of the selected
binding/provider, model, permitted task data, fixed request/token budget, vendor
overage policy and cost ceiling before any model call. If a requested hard
spending bound cannot be enforced under that arrangement, stop for a different
operator decision; do not promise one from a local token limit." The plan says
the same (`docs/plans/milestones/M8-live-executors-rev3.md:143-149`). ADR 0021
adds a sharper rule: `subscription_overage="forbidden"` "requires proved
mechanical refusal at the included limit; if the vendor arrangement cannot
supply that proof, the profile is unavailable" and "Unknown overage control is
not permission to incur it"
(`docs/adr/0021-subscription-executors-bind-operator-stores.md:245-252`). Rev 3
adds: "unknown enforcement cannot qualify an overages-forbidden profile"
(`M8-live-executors-rev3.md:112-113`).

## 1. Codex under a ChatGPT plan

### 1a. Plus and Pro (personal plans)

**At the limit: the default is purchasable credits, not a single hard stop.**
- https://help.openai.com/en/articles/12642688-using-credits-for-flexible-usage-in-chatgpt-freegopluspro-sora :
  "Your plan's included usage is used first. After you hit plan limits, usage draws from your credit balance."
  and "If you hit a usage limit in Codex on Plus or Pro, you'll see an option to add credits."
- https://learn.chatgpt.com/docs/pricing :
  "ChatGPT Plus and Pro users who reach their usage limit can purchase additional credits to continue working without needing to upgrade their existing plan."
- Same page: "All users may also run extra local chats using an API key, with usage charged at standard API rates."
- **The limit is not enforced mid-turn.** Same page: "If you reach your usage limits during an active turn, the agent will be able to continue working on that turn, subject to fair use limits."
  https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan
  says the same: "if you reach a usage limit during an active turn, Codex can continue working on that turn, subject to fair-use limits."
- Paid instant resets (a separate purchase):
  https://help.openai.com/en/articles/20001507-paid-weekly-work-and-codex-rate-limit-resets :
  "Customers on ChatGPT Plus and Pro plans can buy an instant reset from Usage settings in ChatGPT Desktop before reaching a limit, or from an in-app offer after reaching the weekly limit."
  Buying one needs a checkout: "Review the price and payment method in checkout, then complete the purchase."

**Automatic spending and its only documented cap.** From the personal credits article above:
- "If automatic reload is available to your account, you can turn it on from Settings > Usage in ChatGPT or Usage & Billing in the Codex app."
- "we automatically purchase enough credits to return it to your selected target balance, up to any maximum monthly spend you set, using your default payment method on file"
- "The maximum monthly spend applies to automatic reloads, not one-time credit purchases."
- The balance can overshoot: "If a task starts while your balance is positive but finishes after concurrent usage depletes it, your balance can go negative."
- Limits vary by account: "Available purchase amounts, prices, payment methods, spending limits, and feature availability can vary by account, region, and plan."

**Can overage be switched off?** None of the fetched personal-plan pages
documents a setting that stops Codex from drawing on an existing credit
balance after the plan limit. That is a result about the pages read, not
evidence that no such setting exists (see Could not verify). The one
documented spending cap is automatic reload's "maximum monthly spend". It
covers automatic reloads only, not one-time purchases.

**Hard monetary ceiling:** none documented for personal plans. In practice
the bound comes from account state: the prepaid credit balance (which may go
negative in flight) with automatic reload off. The page says reload is
something "you can turn … on". It does not say reload is off by default, so
reading it as default-off is an inference.

### 1b. Business (workspace)

- https://help.openai.com/en/articles/20001155-managing-credits-and-spend-controls-in-chatgpt-business :
  "When that included usage is exhausted, workspace credits can cover additional eligible usage, subject to your workspace’s spend controls."
  and "If your workspace does not have enough credits, features that require credits may be unavailable until credits are added."
- Controls: "Workspace owners and admins can manage monthly credit usage limits by seat type and per-user overrides. Only workspace owners can purchase credits or manage automatic reload."
- Default: "By default, all seats and users have no limits specified."
- Reload cap: "To cap automatic reload purchases, enter a Monthly recharge limit; leaving this field blank allows unlimited automatic reload purchases each month."
- https://help.openai.com/en/articles/11487671-flexible-pricing-for-the-enterprise-edu-and-business-plans :
  "Business: Users see a banner when their included usage is exhausted. If no credits are available in the workspace pool, the feature is blocked and users can ask a workspace owner to add more."
  Also: "Purchasing credits is optional and only necessary if a workspace owner wants to unblock users who exceed their usage limits across any seat type."
- https://help.openai.com/en/articles/12003714-chatgpt-business-models-limits :
  "If you reach an included limit, eligible usage can continue with purchased workspace credits when credits are available and your workspace's spending controls allow it."

### 1c. Enterprise and Edu (credit-based)

- https://help.openai.com/en/articles/20001001-manage-usage-limits-and-overages-in-chatgpt-enterprise-and-edu :
  "OpenAI does not set a workspace overage limit by default. The setting appears as No limit until a workspace owner defines one. If no overage limit is set, certain feature usage can continue being utilized uninterrupted, but could incur unwanted overage charges."
- Same page: "Setting the limit to 0 blocks new requests that use credits once the committed credit pool is exhausted. This does not guarantee that the credit balance stays at or above zero in real time: requests already in progress may finish and settle afterward, leaving a small negative balance."
- Same page: "Alerts do not block usage. Use the workspace overage limit to control additional credit usage."
- Token-based (USD) agreements: "For token-based billing, the monthly workspace budget caps metered ChatGPT spending in USD." and "Without a monthly budget, no workspace budget cap is in place".

### 1d. What the Codex client can observe (pinned `rust-v0.153.4`)

The following is registered and reachable in the pin:
- Request `account/rateLimits/read` (`codex-rs/app-server-protocol/src/protocol/common.rs:1234-1238`) returns `GetAccountRateLimitsResponse`, which has `rate_limits`, `rate_limits_by_limit_id`, `rate_limit_reset_credits`, `account_id` and `rate_limit_upsell` (`codex-rs/app-server-protocol/src/protocol/v2/account.rs:314-325`).
- `RateLimitSnapshot` (`account.rs:565-576`) carries `primary`/`secondary` windows, `credits: CreditsSnapshot { has_credits, unlimited, balance }` (`account.rs:671-675`), `individual_limit: SpendControlLimitSnapshot { limit, used, remaining_percent, resets_at }` (`account.rs:690-696`), `spend_control_reached: Option<bool>` ("Backend-reported spend-control state. `None` is unavailable", `account.rs:572-573`), `plan_type` and `rate_limit_reached_type`.
- `RateLimitReachedType` has these variants: `RateLimitReached`, `WorkspaceOwnerCreditsDepleted`, `WorkspaceMemberCreditsDepleted`, `WorkspaceOwnerUsageLimitReached`, `WorkspaceMemberUsageLimitReached` (`account.rs:599-605`). The client renders the last two as "You hit your spend cap set in your workspace…" and "You hit your spend cap set by the owner of your workspace…" (`codex-rs/protocol/src/error.rs:682-692`).
- The app-server README says `individualLimit` "describes the effective monthly credit limit when available. In an `account/rateLimits/read` response, `null` means no monthly limit is available." (`codex-rs/app-server/README.md:2770`). `account/rateLimits/read` is documented as returning "an optional effective monthly credit limit, whether spend control has been reached" (`README.md:2529`).
- Notification `account/rateLimits/updated` (`common.rs:1907`) is sent from turn token-count events (`codex-rs/app-server/src/bespoke_event_handling.rs:1675-1702`). It is a "Sparse rolling rate-limit update" (`account.rs:551-560`). On the per-request paths, `spend_control_reached` and `individual_limit` are hard-coded to `None`: `parse_credits_snapshot` reads the `x-codex-credits-has-credits`, `x-codex-credits-unlimited` and `x-codex-credits-balance` headers (`codex-rs/codex-api/src/rate_limits.rs:217-228`), and both the header and event parsers set the two spend fields to `None` (`rate_limits.rs:96-97, 162-163`). **Spend-control state is only read back through `account/rateLimits/read`**, which gets it from the backend usage payload (`codex-rs/backend-client/src/client.rs:583-613`).
- Other account methods: `account/rateLimitResetCredit/consume` (spends an earned reset, `common.rs:1240-1244`), `account/usage/read` (`common.rs:1246-1250`; README says it can read "estimated credits, optional cost" per thread, `README.md:2531`) and `account/sendAddCreditsNudgeEmail` (`common.rs:1258-1262`). None of the registered account methods buys credits or changes automatic reload. That comes from the registrations listed at `common.rs:1201-1262` and the retained-binary inventory in `docs/plans/handoffs/M8-native-account-interface-preflight.md:76-80`. A grep for `auto_reload|autoReload|recharge` across `codex-rs` found nothing, so automatic-reload state is not visible to the client.

**Findings about this repository's adapter (for the N5 design, not defects I am filing):**
- **Verified: the turn carries no overage fact at the pin.** At openai/codex `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`, `pub struct Turn` (`codex-rs/app-server-protocol/src/protocol/v2/thread_data.rs:366`) has only `id`, `items`, `items_view`, `status`, `error`, `started_at`, `completed_at` and `duration_ms`, and no `rateLimits` field. A case-insensitive `git grep` for `usingOverage` or `using_overage` at that commit finds no occurrence in `codex-rs/app-server-protocol`, nor in `codex-rs/app-server` or anywhere under `codex-rs`; `git grep` over the same commit and path does find `pub struct Turn {` and `rateLimits` in the generated schemas, so the tree was searchable. Constructicon's `_rate_limit` reads `value.get("usingOverage")` (`src/constructicon/substrate/executors/codex_protocol.py:932`) from `turn.get("rateLimits")` on `turn/completed` (`codex_protocol.py:1030`). Against the pin that argument is always absent, so `_rate_limit` returns `None`, the observation publishes no `RateLimitInfo`, and `is_using_overage` is always `None`. That is truthful under I4, since an unemitted fact stays `None`. It is not overage evidence: **overage evidence for N3c/N5 must come from the `account/rateLimits/read` request, not from the turn.** The adapter's field name matches Claude Code's `isUsingOverage` (see 2c), not Codex's.
- The one in-band Codex spend signal is `account/rateLimits/updated`. The adapter refuses every `account/` notification as a namespace (`codex_protocol.py:536-544`). `docs/plans/handoffs/M8-implementation-record.md:937-945` already names this cost ("a rate-limit update, say"). Under N5 it means a live turn that gets a rate-limit update is refused. So "Subscription limits … remain truthful" (#78 acceptance criterion) needs either the notification or a pre-turn and post-turn `account/rateLimits/read`.
- The `_rate_limit` docstring says "We hold no schema for this payload" (`codex_protocol.py:918`). The pin ships generated schemas, for example `codex-rs/app-server-protocol/schema/json/v2/GetAccountRateLimitsResponse.json` and `.../AccountRateLimitsUpdatedNotification.json`.
- A test uses the name `account/rateLimits/changed` (`tests/substrate/test_codex_adapter.py:840`). Its docstring shows the name is deliberately hypothetical. The pinned name is `account/rateLimits/updated`.

**The two unidentified pre-turn notifications (UNVERIFIED identification).**
The adapter sends `initialize`, `initialized`, `account/read`, then
`thread/start` (`codex_protocol.py:277, 286, 293, 359`). In the pin, the
completion of initialize sends zero or more `configWarning` notifications
(`codex-rs/app-server/src/request_processors/initialize_processor.rs:161-173`)
and then exactly one `remoteControl/status/changed`
(`codex-rs/app-server/src/lib.rs:1080-1093`). `thread/start` sends
`thread/started` (`codex-rs/app-server/src/request_processors/thread_processor.rs:1589`).
The likely pair is therefore `remoteControl/status/changed` plus
`thread/started` (or a `configWarning`). I found no emitter of
`account/rateLimits/updated` before a turn. This comes from reading source,
not from the lane's recorded `withheld_methods`. It is not a measurement.

## 2. Claude Code under Claude Pro, Max and Team

### 2a. Pro and Max

- https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans (dated August 10, 2026):
  "Usage credits allow individuals subscribed to paid Claude plans (Pro, Max 5x, and Max 20x) to continue using Claude seamlessly after reaching their included usage limits."
- Turning credits on is an explicit step: "Click "Enable" to turn on usage credits." and "You’ll then need to prepay to cover usage beyond your plan limits."
- Caps: "Click “Adjust limit” to control costs with a monthly spend limit. You can also select “Set to unlimited” if you prefer no spending restrictions." and "Monthly spending cap: Set a maximum amount you're willing to spend on usage credits each month."
- **Disable:** "Can I disable usage credits after enabling them? Yes, you can disable usage credits at any time through Settings > Usage . Once disabled, you'll only have access to your plan's included usage."
- Same article: "Usage credits apply to both Claude conversations and Claude Code terminal usage."
- https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan (dated August 19, 2026):
  "If you have an ANTHROPIC_API_KEY environment variable set on your system, Claude Code will use this API key for authentication instead of your Claude subscription … resulting in API usage charges".
  Also: "All transitions to API credit usage require explicit user consent." and "To maintain your Pro or Max plan budget, simply decline API credit options when offered."
- **The client can raise the cap:** https://code.claude.com/docs/en/costs : "On Pro and Max plans, when you reach your spend limit with usage credits still available, Claude Code prompts you to raise or remove the limit without leaving the CLI."
- Without credits, the limit is a block: https://code.claude.com/docs/en/errors : "Claude Code blocks further requests until the reset time shown in the message."
- Some requests are billed only to credits. Same page: "or when the request is one that only usage credits pay for, such as a request to a model that bills to usage credits". The 1M-context entitlement: "your plan only includes it through usage credits."
- The pages read do not say whether the Pro/Max monthly spend limit can be overshot (see Could not verify).

### 2b. Team (and seat-based Enterprise)

- https://support.claude.com/en/articles/12005970-manage-usage-credits-for-team-and-seat-based-enterprise-plans :
  "After an organization Owner or Primary Owner configures your account for usage credits, you'll start using them as soon as you reach your seat's usage limit."
- Same article: "Owners and Primary Owners can choose to disable usage credits entirely, which means that members of the organization will be unable to continue working once they reach their usage limits and will need to wait for them to reset."
- Caps: "Setting a limit here controls total usage credit spend across your whole organization, regardless of individual or seat limits." and "Changes to your organization’s overall spend limit go into effect immediately."
- Overshoot: "It's possible to slightly exceed your defined spend limit. Our system checks if you're within your limit before you're allowed to make a single request or send a message. Once the request is processed, we calculate your token consumption, which means you may bypass your limit with that request."
- https://code.claude.com/docs/en/costs : "Cap spend: the seat allowance is the default ceiling. To let members continue past it, turn on usage credits and set spend limits at the organization, group, or individual member level."

### 2c. What the Claude Code client can observe

- Headless stream `rate_limit_event`. From the Agent SDK Python reference, https://code.claude.com/docs/en/agent-sdk/python : `RateLimitEvent` is "Emitted when rate limit status changes". `RateLimitInfo` has `overage_status` ("Status of pay-as-you-go overage usage, if applicable"), `overage_resets_at` and `overage_disabled_reason` ("Why overage is unavailable, if status is "rejected""). `RateLimitType` includes `"overage"`.
- A user report (secondary source, not vendor documentation) shows the CLI's raw event: `"overageStatus":"allowed" … "isUsingOverage":false` (https://github.com/anthropics/claude-code/issues/78476).
- Status line: https://code.claude.com/docs/en/statusline : "rate_limits : appears only for claude.ai Pro and Max subscribers, or behind a Claude apps gateway that sets a spend limit for you, and only after the first API response in the session." It exposes `five_hour`, `seven_day` and a gateway-only `spend_limit`. There is no overage or credits-enabled field.
- Interactive `/usage` (costs page): "/usage also shows a usage-credits row while usage credits are on." For Pro and Max: "When you haven’t set a limit, the row shows Unlimited and no spend figure." The sentence "While usage credits are off for you, /usage shows no usage-credits row" appears in the Team/Enterprise bullet, so it is unclear whether it also covers Pro/Max.
- Unattended behaviour, errors page: "Claude Code fails at once when a standard-speed request gets a 429 that reports a spend limit or exhausted usage credits".

## 3. Conclusions per provider

**Codex / ChatGPT Plus or Pro.** No vendor-side setting that forbids overage
was found. The only documented cap ("maximum monthly spend") covers automatic
reloads only. Any bound comes from account state: no purchased credits and
automatic reload off. Nothing in the vendor configuration locks that state,
and even with it, the vendor documents in-turn continuation past the limit
and negative balances. Under ADR 0021, a `forbidden` profile has **no vendor
proof of mechanical refusal** here. It could be recorded only as "forbidden,
enforced by zero balance and reload off at time T". That is observed state,
not an enforced control, and it is weaker than what ADR 0021:245-248
requires. **Recommendation: stop for an operator decision** (issue #78's
branch). Either accept that weaker record explicitly, or choose a Business
workspace.

**Codex / ChatGPT Business or Enterprise.** A vendor-side control exists and
is a positive fact. Business has per-seat and per-user monthly credit usage
limits, plus "If no credits are available in the workspace pool, the feature
is blocked". Enterprise has an overage limit of 0, which "blocks new
requests". Both admit in-flight overshoot, so the bound holds at request
admission, not to the cent. The client can read it back:
`account/rateLimits/read` shows `individualLimit` and `spendControlReached`.
Whether Business accepts a per-user limit of 0 is not stated.

**Claude Code / Pro or Max.** A vendor-side positive fact exists: usage
credits can be disabled, and "Once disabled, you'll only have access to your
plan's included usage." Two conditions must also hold. The CLI must have no
`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` or `apiKeyHelper`, and must be
pinned to claude.ai login. The in-CLI prompt to raise the limit applies only
while credits are on.

**Claude Code / Team.** The Owner can disable usage credits, and the seat
allowance is the documented default ceiling. Both are positive facts. Spend
limits, when enabled, may be "slightly" exceeded.

### Evidence that would let the operator record overage as "forbidden and enforced"

Smallest sufficient set, written at authorization time into the N5 record:
1. The vendor rule quoted with URL and retrieval date. For Claude this is the
   "Once disabled…" sentence. For Codex Business/Enterprise it is "feature is
   blocked" or "limit to 0 blocks".
2. An operator-captured view of the vendor settings page for the bound
   account or workspace, with non-secret parts only:
   - Claude: Settings > Usage shows usage credits **disabled**. For Team, the
     admin Usage page shows credits disabled for the org.
   - Codex Business/Enterprise: Workspace settings > Billing shows the
     per-user or seat credit limit, or the overage limit at 0, and automatic
     reload off or capped.
   - Codex Plus/Pro: Settings > Usage shows a credit balance of 0 and
     automatic reload off. Record this as state, not a control.
3. A client-side readback in the same session as the run, before and after
   it, recorded as bounded non-secret values:
   - Codex: `account/rateLimits/read` showing `credits.hasCredits=false`
     (personal), or `individualLimit` present with `spendControlReached`
     (Business). This is an authenticated `account/` request, so the N5
     authorization must name it. The turn record cannot substitute: at the
     pin it carries no overage field (1d).
   - Claude: an observed `rate_limit_event` whose `overage_status` is
     `rejected` with an `overage_disabled_reason`. If no event is emitted,
     record the readback as UNVERIFIED.
4. Credential-path exclusion: no API key in the environment, per ADR 0021's
   mode proof.

YAGNI. Considered and rejected as unnecessary:
- a local spend meter or token-to-dollar estimator (the issue forbids
  promising a bound from local limits);
- continuous polling of `account/rateLimits/read` or `account/usage/read`
  during a turn;
- a new overage-policy state beyond the two sealed values;
- automating the vendor settings capture.

The pre-run and post-run readback plus the operator attestation is the
smallest set that meets ADR 0021 and #78.

## Could not verify

- Whether personal Plus/Pro accounts have any setting that stops drawing on
  an existing credit balance. None was found in the pages read, which is
  absence of evidence only.
- Whether automatic reload is off by default on Plus/Pro. The docs say "you
  can turn it on".
- Whether the in-turn continuation past the included limit ("continue working
  on that turn, subject to fair use limits") is billed to credits.
- Whether a ChatGPT Business per-user credit limit of 0 is accepted and
  blocks all credit use.
- How far a negative balance or overshoot can go on any Codex plan. It is
  called "small" only for Enterprise.
- Whether the Pro/Max monthly spend limit can be overshot. Overshoot is
  documented for Team only.
- Whether `rate_limit_event` is emitted at session start, or only on status
  change. The doc says "when rate limit status changes". Also unverified:
  whether `overage_status: "rejected"` reliably means credits are disabled.
- Whether the `/usage` "no usage-credits row when off" sentence applies to
  Pro/Max.
- Which two notifications are the CI pre-turn ones. Candidates come from
  source reading only.
- That the backend actually populates `individualLimit` or
  `spendControlReached` for a given account. The source marks both optional.
- Whether ChatGPT "Team" is now the plan named "Business". Only Business
  pages were fetched.
- Vendor pages change daily (several had been updated within hours of the
  fetch), so every quote needs re-fetching at authorization time.
- The GitHub issue content (#78476, #50518) is a user report, not vendor
  documentation.
