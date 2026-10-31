# Claude subscription mode: replace display-tier identity

Status: proposed; no implementation or live execution authorized by this document.
Refs #40. Observed controller: 08de69f542b759fa3badd56515b709dd3ef7ddb0.
Pinned native member SHA-256:
24972e3bc859fab2b46ed4c1e51f7d6130f06d3bd550811a114640de3370d0de
(Claude Code 2.1.296).

This is an additive successor proposal for the exact display-tier comparison in
[M8-N6a-state-review](M8-N6a-state-review.md) and the Pro/Max-only managed-policy
argument in [the fixed startup contract](M8-N6-fixed-startup-contract.md).
Those accepted documents remain unchanged. ADR 0021's supported subscription
observation, native-store custody and physical authority requirements remain.

## Observed problem

The [generation-12 recovery](https://github.com/sushiHex/constructicon/issues/77#issuecomment-6537185562)
checked a valid failed attempt: no dispatch, zero callbacks, both binding checks
passed and relay closed. NodeFailed reports initialization mode-mismatch with
subscription-mismatch and absent token/API-key source fields. The exact reported
label and failing initialize ordinal were not collected.

The pinned source demonstrates an independent defect in the contract assumption.
Initialization publishes a display string, not a stable commercial-tier identity:

| Producer | Binary byte offset | Fact |
| --- | --- | --- |
| kr | 210444781 | Reads the process's structured subscription state. |
| Zk / Dvr | 210446011 / 210446100 | A valid server planDisplayName overrides the fixed tier label whenever the structured value is non-null. |
| xRe | 210449537 | Publishes subscription only on the native inference-scoped OAuth branch. |
| initialize account | 233773025 | Exposes the display-derived subscription string. |
| auth status | 234958863 / 234960064 | Exposes kr's structured enum, but in a separate process. |

A Max subscription can therefore report a different display string without a
tier change. Conversely a different tier with display name Max can report
Claude Max. Exact display equality is neither a complete availability rule nor
a source-backed tier discriminator. This source mechanism is not proof of the
specific value or refresh timing in generation 12.

Separate-process auth status is not a substitute for the executing process:
OAuth refresh can change its memoized state. Do not delete profile fields,
prevent normal profile writes, inject a tier override or infer tier from a name.

## Proposed contract

Judge subscription authentication class, independently of marketing tier.
A same-process initialization observation must still satisfy every existing
framing, correlation, idle, pending-action, account-shape, provider and
credential-source guard. Its subscription representation must be one the pinned
producer can emit on the inference-scoped subscription branch; Claude API and
missing, malformed or unknown authentication projections refuse.

The predicate must be specified from the producer, including its bounded
display-name grammar. A generic prefix check is not the specification.
Do not publish raw account/display values or report an inferred commercial tier.

Qualification selects a subscription-mode compatibility profile, not a
commercial-tier assertion. A user must not select an inaccurate Pro/Max label
to use another compatible subscription. If tier information remains as user
intent, separate it from observed authority and never represent it as measured.
Replace affected strict evidence shapes with an explicit new revision; preserve
historical evidence as historical and require fresh qualification and binding.

Compatible subscriptions share the same positively proved startup and
authentication contract. They do not gain an exception from hooks/settings,
tool filtering, physical isolation, worker admission, deadlines or terminal
checks. Preserve both initialization exchanges and the actual MCP handshake.

## Required producer and lifecycle proof

These are explicit proof obligations, not claims that implementation is ready.

1. **Authentication route.** B$n (211113589) tests enabled first-party OAuth and
   user:inference; sSs (211113673) selects no API key for that route. Model-client
   construction (211571313) checks the post-refresh memo. The initialize
   projection uses the same predicate (wt, 210441977; JGn, 207482285).
   Cover missing/malformed raw tier, display override, scope changes and all
   alternate authentication routes in credential-free fixtures.
2. **No billed-key fallback.** Retain clearenv and the exact native environment,
   fresh config/HOME/SDK directories, fixed admin policy and absence of profile
   stores. Prove all key/header/helper sources absent throughout the acquisition.
   Before launch, positively refuse the absolute remote-key/token paths
   /home/claude/.claude/remote/.api_key and .oauth_token in the runtime view.
   Do not infer their absence from the builder: dependency paths are dynamic.
   Couple that guard to the exact runtime digest and mount recipe.
   The source's both-null SDK client must refuse before sending. The writable
   credential FD is not an immutable credential snapshot.
3. **Initial policy.** Reuse the forced loader, effective-settings/hooks checks,
   and synchronous retained-snapshot replay in the fixed startup contract.
   Cover eligible null settings, a non-null eligible payload and checked static
   fallback, not just Pro/Max's ineligible branch. Effective settings after the
   join must contain no apiKeyHelper and no key/token/header/base-URL/provider
   environment override. Cover every merged source, including remote policy.
   Non-null helper-bearing input must either refuse or be proved inert under
   the initial-pass and no-further-exec/fallback rules; resolved settings alone
   cannot prove raw helper configuration absent.
4. **Ordinary polling.** The first real poll follows a one-hour setInterval
   (224508584, 224541421, 215247161), beyond the independent nonrenewable
   acquisition/supervisor deadline. A configured timeout alone is insufficient.
5. **Helper retries.** Short helper timers exist. New output requires
   It -> Zi -> ct -> ve -> Xut -> child_process.spawn (209432140,
   209221709, 209225268, 207777722). Existing physical no-further-exec must
   prevent success. Failed retries preserve the checked fallback exactly
   (209409450); notifications alone do not establish payload changes.
6. **Auth/source changes.** Remote refresh call census must exclude all later
   sources of new policy payload. Routine token refresh has no Nhn call.
   Explicit login is outside the READ command set. Sibling-login refresh belongs
   to a private interactive controller; prove the --print path returns into
   runHeadless before that controller is constructed, including queued work.
   Do not infer exclusion from an empty event list.

The source census must account for every publication path at each await,
including already queued startup replay and failed retries. One unclosed path
keeps compatibility unproved. Do not substitute repeated authenticated READs.

## Delivery boundary

Approve this successor only after the producer and lifecycle source proof
closes and the physical absence/initial-settings guards are specified.
Implementation must affirm those guards with accepting/refusing tests and the
affected native proof before any new qualification or live attempt. Then implement the single shared mode
judge and its qualification/READ consumers with accepting and refusing tests,
focused mutations for changed guards and one consequential boundary review.
Reuse the existing physical startup lane; no credentials or local vendor runs.

A new adapter/qualification revision requires reviewed installation and fresh
qualification before live use. At most one separately selected READ may follow
its actual candidate review. This proposal supplies no login, refresh, model
call, WRITE, deployment or retry authority.

## Source census disposition

Independent source review established the route equivalence, the both-null SDK
refusal, initial policy join/replay, the actual first poll timing, and the helper
runner's fresh-spawn requirement. Failed helper retries retain the admitted
fallback; they are not excluded merely because ordinary polling is hourly.

Remote refresh Nhn is reached from startup, explicit login, and interactive
sibling-login adoption. Routine token refresh has no Nhn call. The fixed READ
input set contains no login control. The print route returns prepared-headless
into runHeadless before interactive UI construction (209335379, 225800184,
225509267, 225543858, 225736793, 225708910). The sibling watcher belongs to
private controller i1, constructed only by private React component aRe; neither
is exported (238623477, 239972131, 2400007xx). Loading that module is not
controller construction. This closes that caller without assuming credential
immutability or own-write filtering.

The API-key global-config writer is reached only by login completion without
inference scope (210418693, 210471130, 233066687). The fixed READ command set
does not invoke it. New global config/HOME/SDK directories and clearenv are
mechanical recipe facts (linux.py:650-686; claude_native.py:30-66).
The credential FD itself is writable; no proof here assumes otherwise.

These source facts justify the proposed contract, not historical authentication
values or a completed implementation. The new root-absence guard, effective
settings matrix, changed evidence revision and physical acceptance remain
implementation gates. A hypothetical malformed persisted tier must never be
published as a measured tier; subscription routing is proved from the inference
scope branch and fail-closed absence of all alternate billing sources.
