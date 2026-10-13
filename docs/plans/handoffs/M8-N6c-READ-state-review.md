# M8 N6c — pinned READ protocol and state review

Investigation for [#174](https://github.com/sushiHex/constructicon/issues/174),
under [#40](https://github.com/sushiHex/constructicon/issues/40),
[ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md) and
[M8 rev 3 N6](../milestones/M8-live-executors-rev3.md).
This is a pre-implementation review, not a startup qualification or permission
to run a vendor process. The current disposition is **mode interface supported;
full startup predicate not yet established**. This does not show that the
pinned client is incapable of qualification.

## Evidence boundary

The pin remains CLI **2.1.296** / SDK **0.3.296**, not a floating latest version.
The public artifacts and tarball identities are recorded in the
[N6a source review](M8-N6a-state-review.md#current-source-pin-inspected-without-execution).
On 2026-10-13, the cached extracted members were independently rehashed:

| Member | SHA-256 |
| --- | --- |
| Linux `package/claude` | `24972e3bc859fab2b46ed4c1e51f7d6130f06d3bd550811a114640de3370d0de` |
| SDK `package/sdk.d.ts` | `fc2866dfe2c01468edb19b1d94f26156bfacecdf1e7f1452b276ed2f8cc0b08f` |
| SDK `package/sdk.mjs` | `5cf6f15237f9c84e6e5b724a10180478732457168921d7aa3e02632037cce299` |

`B@` below means a zero-based byte offset in that Linux member; `S@` means a
byte offset in `sdk.mjs`; `D:` means a one-based line in `sdk.d.ts`. Minified
native source is inspected as bytes, never executed or imported. These are
source observations, not live behavior, installed identity or credential proof.
No private host, login store, account or model was used.

## Supported protocol facts

- Repeated `initialize` is a supported fresh control request, not the SDK's
  cached `accountInfo()` accessor (`D:2994-3020`; `S@1189034`). Native `YL`
  (`B@233767913`) takes a distinct repeated branch and calls response builder
  `Vg` (`B@233772528`), which invokes the account projection again. Calling the
  projection again does not, by itself, prove expiry detection or fresh
  underlying credential state.
- Bare repeated initialization is not generally an inert getter. The same
  branch can redeliver pending requests and contains hook/state operations.
  Only fields whose absence has been traced may be treated as inactive. The
  adapter must not use the SDK's hook-bearing reconnect convenience as a
  substitute for an audited bare request. Two suspected new side effects are
  inactive when omitted: `xC` (`B@233563291`) returns for a nonboolean
  proactivity value, and `Yf` (`B@233406904`) requires an exactly true Chrome
  setup-offer flag. These are not blockers to a bare repeated request.
- `system/init` is turn metadata, not the pre-dispatch gate (`D:5970-6000`).
  Its tool list can corroborate a previously established catalog; it cannot
  authorize a user message already sent to obtain it.
- `get_context_usage` has an explicit `detail: "summary"` variant avoiding
  per-category token-count calls (`D:3975-3980`). Its response distinguishes
  MCP tools, deferred built-ins and system tools in the declaration
  (`D:4019-4040`), but **the native producer omits the latter two fields**,
  as traced below. The declaration alone is not an accepting wire fixture.
- SDK-hosted MCP uses `mcp_message` with a server name and nested JSON-RPC
  message, in both directions (`D:4746-4758`). It is not Codex's callback
  envelope. MCP handshake traffic is not authority to execute a worker;
  `tools/call` requires a separately validated admitted operation.
- A result terminates a turn, not necessarily the process. Later informational
  messages may follow (`D:5786-5789`). A success subtype also has an `is_error`
  field; result acceptance cannot test the subtype alone. Usage/cost fields
  have different scopes and omissions (`D:5835-5883`); a cost estimate is not
  a billed amount or a hard spending limit.

## Mode projection and expiry are different observations

The mode audit supports repeated bare initialization as a candidate pre/post
current-session mode observation, not a categorical cache blocker. Native
model-client selection (`B@211571313`) and account projection use the same
OAuth-enabled/scopes predicates; `B$n` (`B@211113589`) tests the inference scope
and `sSs` (`B@211113673`) selects no API key for that OAuth route. The request
refresh path through `joe` (`B@210437024`) checks for credential changes and
invalidates the cache when detected before refresh handling (`Lk`,
`B@210427190`); unchanged usable cached state may remain. This is evidence about
route selection in the pinned source, not vendor-principal continuity or a
physical no-fallback qualification.

Do not reject this interface merely because current selected state is cached:
a fresh projection of invalidated/current state is not the SDK's cached
initial/claimed-session initialization answer. Conversely, the projection alone
does not test credential expiry or prove refresh occurred. Those are separately
required qualification cases, never supplied by an `idle` reply.

`get_usage(skip_behaviors=true)` is not a repair for that distinction. The flag
omits the transcript scan (`D:4277-4282`; handler `B@232989261`), but its rate
limit path can use a snapshot younger than 60 seconds (`B@228816727`,
`B@211619900`) or seeded/header/persisted fallback data, including a persisted
snapshot up to an hour old (`B@228815450`, `B@211619547`). The public result
omits the internal source/status/fetch-time distinctions (`Mhn`,
`B@228818005`). An uncached path can perform OAuth refresh and a network fetch;
the control request does not force that path. It cannot be labeled a fresh
authenticated round trip or used to infer successful refresh from returned
utilization. Missing or stale observations remain unknown.

## Startup shortcuts that do not establish authority

The pin has tools/configuration controls, but their existence is not the full
accepting predicate for a subscription launch:

- SDK `tools: []` documents removal of built-ins (`D:1640-1648`), and CLI
  `--tools` accepts an empty set (`B@225725650`). This needs the actual catalog
  construction and later additions traced; the old pin's observation cannot
  establish the new pin's effective set.
- `--bare` is not a subscription-preserving isolation recipe. Its declaration
  (`B@225719994`) explicitly excludes OAuth/keychain authentication and selects
  API-key/helper or third-party authentication. It must not be used to simplify
  this subscription adapter's startup proof.
- `--safe-mode` preserves authentication but leaves managed policy and built-in
  tool/plugin behavior active (`B@225720650`). It is not an all-tools-off or
  account-configuration exclusion fact.
- `EndConversation` eligibility (`v7n`, `B@230397749`) depends on the feature
  configuration as well as model/entrypoint checks. A headless entrypoint alone
  does not prove exclusion when a remotely selected entrypoint pattern can
  change. The exact flag-client/cache/settings behavior must be included in
  the fixed recipe's source closure, not inferred from its default pattern.

Current source provides useful parts of the closure: an explicitly empty
`--tools` argument records `builtInToolsDisabled` and an empty launch-kept set,
through `t2r` (`B@223700256`, assignments at `B@223703257` and
`B@223703319`); the plugin runtime registration path refuses that disabled state
(`B@217913316`). `get_context_usage` has a native control handler
(`B@232988517`, dispatched at `B@233020497`), and `get_settings` has a native
handler (`B@233738416`) using the merged settings/source projection
(`B@209450024`). These are positive source facts, not proof that the displayed
settings and tool rows cover every launch/remote-flag authority input or remain
closed through a turn.

### Confirmed gap: omitted inventory is not an empty catalog

The handler passes through `Yie` (`B@222729423`), which calls `hAn`
(`B@217708802`). `hAn`'s result explicitly sets `deferredBuiltinTools` and
`systemTools` to `undefined` (`B@217714304`), along with prompt-section detail.
JSON serialization omits them. A further conditional wrapper in `Yie` also
omits the fields; it does not restore a complete catalog. MCP rows remain.
Both the audit and the independent orchestrator read this producer chain.

Thus a permitting fake with affirmative `systemTools: []` and
`deferredBuiltinTools: []` would not be grounded in this inspected route.
Missing fields cannot pass an exact empty-built-in check. Summary token/category
counts and the later `system/init` are not substitutes for that pre-dispatch
fact. This is a limitation of this proposed observation path, **not** proof
that every supported route or mechanical restriction is inadequate.

### Startup model probe: one exclusion established, not all helpers

The current quota probe still has a model-request body (`Dm`, `B@211614135`),
but `probeQuotaStatus` (`B@211625256`) returns before it when `Ee()` is true.
`Ee` (`B@207222231`) means the launch is not interactive. The headless quota
path is therefore source-excluded at this pin; the old screen's exclusion was
not simply inherited. Nonessential-traffic suppression is another early guard.

This does not close the complete pre-dispatch helper inventory. The startup
sequence around `B@225535475` also schedules `Fgt(nae)`, `Wss` and `fRe` before
later MCP setup; their full authority/call closure was not established in this
pass. Do not reinterpret that untraced work as either harmless or a confirmed
model call. The next audit must map it to concrete excluded or bounded helpers.

## Existing seams, not new abstractions

The task boundary remains `core/executor.py:Executor.execute`, accepting
`TaskSpec`, `WorkspaceView | None` and `EffectiveGrants`, returning the existing
`ExecutorOutcome`. No provider enum, session service, new scheduler, generic
stream engine or alternative grant language is proposed.

`core/process.py:ProcessIO` owns bounded reads, cumulative-budget writes and
stdin close inside `LinuxLauncher.exchange`. It supplies neither read-nowait
nor arrival timestamps. Host-created unpredictable IDs and checking all bytes
already received reject stale correlations that the adapter can observe; they
do not authenticate the vendor or prove physical arrival freshness for unread
OS/launcher buffers. No sleep or polling interval supplies that missing fact.

N6b's `ClaudeInitialization` cannot become the prefix of a live conversation:
its completion requires stdin close and actual EOF. The future persistent
conversation may reuse N6a's pure judgment, not N6b's completed lifecycle.

For READ workers, reuse a `ContainedWorkspaceProvider` assembled for READ,
`owned_view` and the view's `use()` guard, then the existing launcher with
`posture=READ`, the owned workspace and remaining acquisition deadline.
`codex.py:_run_worker` is WRITE-specific; importing it would import the wrong
contract. Its ownership pattern is a reference, not a Claude implementation.
The native side receives no workspace. A raw caller-authored path never
substitutes for a provider-minted view and its invocation/epoch checks.

## Conditional one-READ transaction

The following is a design obligation, **not implemented behavior**. It requires
an audited fixed startup recipe and catalog, fresh session mode observations,
and qualified physical store/egress assembly before any live use. A fake may
prove the transaction but cannot supply those native facts.

Use one private monotone phase and affirmative evidence produced at each
boundary, not independently assignable `startup_ok` or `gate_completed` inputs:

`new -> startup -> ready -> dispatched -> terminal -> checked -> drained`

Any failure/reentry/cancellation latches refusal for the acquisition; a late
reply cannot restore an earlier phase. Publication additionally requires the
same exchange's joined clean process result and the terminal binding check.
There is one user-message write attempt, marked spent **before** awaiting it.
An interrupted write may have delivered a prefix or all bytes; never retry,
refund, or reconstruct a second conversation in this acquisition.

| Boundary / await | What may already exist on resumption | Required decision |
| --- | --- | --- |
| Acquire store/workspace guards | Successor closure, cancellation, changed active generation | Recheck owned acquisition, physical binding and sealed revision before materialization or exposure. |
| Startup control write | Delivered prefix, buffered unsolicited record, cancellation | Spend once before write; check poison afterward; no retry and no user dispatch. |
| Read / frame startup | Partial UTF-8, several frames, pending MCP handshake, callback or EOF | Sole reader; bounded private framing; audit received surplus before advancing. Only exact handshake methods may be answered; workers stay closed. |
| Complete startup observations | Mode match but missing config/catalog/binding fact | Require the conjunction affirmatively. Idle state, empty queues and lack of faults are not clearance. |
| Write user message | Full delivery despite drain failure; immediate reply | Mark dispatch spent first. Failure cannot dispatch again. Bind result to the host's one send and session under the pinned protocol. |
| Read callbacks | Duplicate/cross-session/unknown ID, wrong catalog, terminal result in the same buffer | Validate identity, exact operation/schema, bound and sealed grant; spend the call ID and record admitted-started before the first worker await. No raw native command or path becomes host authority. |
| Await worker and native reader | Worker complete plus EOF, damage or terminal native result | Keep one reader. Observed native termination/damage defeats a callback response even when the worker also completed. Join worker before releasing guard. |
| Write callback response | Delivered response with failed drain; late next callback | One response attempt, no retry. Record admitted-completed only after successful worker completion and the complete response write. Recheck phase; account for received bytes, not only already decoded frames. |
| Read result | Final text without a valid terminal envelope; queued or background work | One correlated terminal result, no active callback, exact allowed result shape. A result is not process completion or full accounting. |
| Terminal mode/config/binding checks | Pending callbacks redelivered by initialize, changed mode, late output | No new task or worker authority. Require each terminal observation; failure discards successful output. |
| Close stdin / drain | Additional result, request or informational record, deadline | Publish nothing yet. Classify each permitted tail record explicitly; actual EOF is required, not silence. |
| Return from launcher / cleanup | Nonzero or missing payload status, timeout, teardown error, late cancellation | Require same-launch successful joined result and all gates; preserve cancellation/failure and truthful bounded partial evidence. |

If a worker/read race is used, cancellation of the losing read is not evidence
that it consumed no bytes. Either retain the sole pending read or observe and
account for its completed bytes before another read or response. Join all
owned tasks; do not discard exceptions during cancellation. Every resumed
await checks the irreversible refusal state before further protocol output.

One absolute deadline bounds the acquisition; each worker receives only its
remaining time, never a renewed deadline. The native exchange's cumulative
input/output limits include initialization, callback responses and terminal
checks. Each sequential worker has its own sealed per-call limits: the existing
launcher does not share a byte counter across separate launches. Finite callback
count and aggregate-retention bounds additionally bound their combined work and
published evidence. Callback argument/result and framed-record bounds must be
sealed policy with binding test inputs, not runtime-learned maxima. No token,
backend-request count or monetary ceiling follows from one user-message write.

## Proof obligations if the implementation gate clears

Tests must exercise both Pro and Max accepting paths, not only refusals. Their
positive result requires startup facts, exactly one successful dispatch write,
an admitted READ callback with a joined worker, a correlated terminal result,
fresh terminal checks, EOF and clean joined launch. Also permit a valid
zero-callback task without inventing a worker result.

Inject failure/cancellation/reentry at every row above. Particularly pin
coincident worker/EOF completion, already-buffered terminal bytes, uncertain
dispatch/response writes, duplicate callbacks, terminal-check redelivery,
unknown auth/config, and a clean exit whose acceptance phase never ran.
Walk every public field, including accepting outcomes and exception chains,
against its declared bound/privacy rule. Intentional task output and private
account/control metadata need distinct contracts, not a blanket sanitizer.

One assertion-killed mutant per new guard; an error or unexecuted test proves
nothing. Fixed nonvendor processes in the existing physical lane must prove
native/worker joins, read-only workspace and network exclusion, shared deadline
and cancellation. These are physical fake proofs, not Claude conformance.
No vendor binary execution is part of this wave.

## Implementation disposition and review corrections

Do not add a permitting READ driver yet. The missing prerequisite is an exact,
source-grounded startup accepting predicate and its fixed launch recipe, not
an absent task/process abstraction or an impossible mode interface. A supplied
`startup_ok`, an empty catalog, or a fake-only configuration invented for the
test would skip the requirement this slice was meant to establish.

This is a narrower hold than production qualification: once that predicate is
specified, credential-free implementation may proceed while physical Claude
store/egress, refresh, expiry and live behavior remain separately unqualified.
Conversely, a physical fake launcher cannot fill the source gap. No new READ
tests or mutants are claimed, and no new physical evidence was produced here.

The independent design pass found two introduced specification defects, both
corrected before implementation: callback IDs must be spent before the worker
await, and separate worker launches do not share the native launcher's byte
counter. They share the remaining deadline, with explicit per-call and
aggregate bounds. The corrected state design has no outstanding finding.

Source review also corrected two overclaims: credential-cache invalidation is
conditional on change detection, and SDK initialization is cached for the
initial/claimed session, not immutable across a later claim. The suspected
bare-initialize proactivity/Chrome side effects were refuted by their actual
absent-field guards. Cache presence alone was rejected as a mode-interface
blocker; source selection and invalidation, not the word "cache", decide that.

## Narrow successor acceptance

[#175](https://github.com/sushiHex/constructicon/issues/175) carries follow-up
status; this is the missing evidence contract, not a second task ledger.
Before a permitting fake READ implementation:

1. Define one subscription-preserving, fixed argv/environment/settings/mount
   recipe. Trace its startup helper inputs and managed/feature configuration
   to exclusion or bounded authority before any user-message write. Do not
   substitute `--bare`, `--safe-mode`, or an unexamined headless default.
2. Establish the exact allowed tool set by a supported pre-dispatch observation
   **and/or a source-proved mechanical restriction at its point of use**,
   with no widening from later plugin/managed/feature inputs. Account for the
   confirmed omitted inventory fields; do not weaken ADR 0021 to accept them.
   A replacement approach needs review of its positive accepting predicate.
3. Bind that predicate to the actual fake transcript/configuration and this
   reviewed one-READ state design. Only then write the permitting/refusing
   transaction, assertion mutants and fixed-worker physical proofs. Production
   availability remains refused pending its independent native qualification.

No new owner policy decision is inferred or requested by these source gaps.
Frozen plans, accepted ADRs and Codex code are unchanged. A future proposal to
weaken a required proof would need a separate decision; this record does not.
