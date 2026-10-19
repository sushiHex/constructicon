# Pi workspace READ adapter: bounded fake-first design

Status: **proposed, not accepted**. Design preparation authorized on 2026-10-19;
implementation, Pi execution, credentials, model requests and deployment are
not authorized by this document. Owner: [#42](https://github.com/sushiHex/constructicon/issues/42).
The completed [source screen #257](https://github.com/sushiHex/constructicon/issues/257#issuecomment-6276054659)
is source evidence, not qualification. No proofs proposed below have run.

## Authority and decision boundary

Preserve [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md),
[accepted M8 rev 3](../milestones/M8-live-executors-rev3.md),
[ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md) outside
the explicit v3 exception, and [the invariants](../../INVARIANTS.md).
The frozen rev-3 draft header is historical, not a new acceptance decision.
This proposal does not amend N6-before-N7, remove #42's Claude dependency,
replace either required subscription adapter, close M8, or advance M9.

The proposed first deliverable is a credential-free **workspace READ** adapter
with a scripted Pi-shaped subprocess peer, not a text-only/no-tools substitute.
It reads an actual admitted immutable workspace and returns bounded analysis
through the ordinary task/outcome seam. Its peer, model and authentication are
simulated; the Linux proof would exercise real containment with that peer.
No real Pi provider descriptor becomes available from such evidence.

One important constraint: Pi's own `read` tool in a process with a workspace
must not be combined with a subscription-store mount and called ADR-0021 v3.
That decision's native zone has **no workspace**; its worker has **no store or
egress**. The existing launcher also refuses store and workspace co-mounting.
A future v1 provider-route candidate must keep credentials out of the child;
a future subscription candidate needs its own eligible supported route and
mediated worker design. Neither is selected or implemented here.

## One candidate, existing contracts

Use one L1 protocol decoder and one L1 adapter/provider, assembled by L4. These
are proposed adapter modules, not a new L0 protocol, provider switch in the
walker, process manager, event bus, gateway or workflow language.

| Existing contract | Proposed use |
| --- | --- |
| `TaskSpec` / `Executor.execute` | One instruction; initially reject nonempty `context` and non-`None` `response_schema` before launch, as unsupported rather than silently dropping them. Return ordinary text analysis; `structured_output=False`. |
| `WorkspaceView` / `GitRef` | Require the admitted READ workspace and retain its exact commit identity. Assembly supplies its locator; prompt text never selects a host path, mount or authority repository. No new workspace abstraction. |
| `ExecutorProfile` / `ExecutorGrantPolicy` | Fake-first v1 profile: READ only, exact tool set `("read",)`, `network_modes=("none",)`, `network_access="none"`, `environment_names=()`, `workspace_required=True`, `accepted_efforts={"off"}`. Isolation is `read_only_snapshot`, owned process tree, allowlisted environment and enforced network. Delegate pure checks to `profile.grant_faults`; additionally require explicit fixture model `fixture/pi-read`, effort `off`, supported task shape and workspace. No backend-default or automatic provider fallback. |
| `ExecutorProvider` / `ExecutorLaunchIdentity` | A genuine fake publishes only its own identity and evidence. Bind its actual fixture executable/runtime, decoder, adapter, configuration, limits and launch law; `provider_route=None`. Real Pi availability stays absent/unavailable, never enabled by a fake pass or placeholder conformance digest. |
| `LeasedCapability` / `AcquiredCapability` | Acquire inertly with complete recovery identity; record/enroll before `materialize`. Reuse acquisition guards, close/reconcile and the walker's `LeaseContext.check_control`; no second lease ledger. |
| `ProcessIO` / `LinuxLauncher.exchange` | One owned byte conversation, one reader plus at most one writer, same absolute deadline and bounded capture. No `RpcClient` subprocess manager, retained handle or renewed conversation. `vendor=None`, no native store or egress route in the fake READ launch. |
| `ExecutorOutcome` / journal / `RunHost` | Existing success/partial/failure union, ordinary checkpoint and restart rules. No new error kind, journal schema or scheduler. A checkpoint avoids another dispatch; uncheckpointed computation may repeat in a fresh acquisition. No exactly-once computation/cost claim. |

Contract sources: [executor](../../../src/constructicon/core/executor.py),
[workspace/leases](../../../src/constructicon/core/workspace.py),
[byte conversation](../../../src/constructicon/core/process.py),
[launcher](../../../src/constructicon/substrate/executors/linux.py), and
[contributor rules](../../CONTRIBUTING.md#adding-an-executor-l1).
The existing `FakeExecutor` touches no workspace: it is useful for seam
substitution but is not the proposed READ-process positive witness.

## Fixed startup, resources and tools

Reference source is `earendil-works/pi@28bea006be4adb950dcb4f86f9ee5be857bf74ff`.
It is not an approved executable build. No package install or real Pi process
is part of preparing this design. The fake peer must capture and assert the
proposed startup inputs; it must not pretend to prove Pi honors them.

The candidate production recipe to prove later is one fresh RPC session,
explicit provider/model and `--thinking off`, with no resumed session, initial
positional prompt, `@file` attachment or implicit model selection. Select
`--tools read`, `--no-mcp`, `--exclude-tools 'mcp__*'`, `--no-extensions`,
`--no-skills`, `--no-prompt-templates`, `--no-themes`, `--no-context-files`,
`--no-approve` and `--offline`; supply no explicit extension/resource paths,
custom extension factories or unknown flags. These are fixed assembly inputs,
not graph/model-supplied options. Exact executable/session/config arguments
must be bound to a future reviewed build, not guessed from these names.

Start in the admitted `/workspace` READ mount with a disposable empty home and
agent/config/session state, fixed immutable runtime and fixed minimal settings.
Exclude inherited environment, API keys, provider overrides, proxies, package
sources, extension/MCP settings and ambient parent directories. Only trusted
assembly chooses those inputs. Workspace content is untrusted data; the flags
must prevent its project instructions/resources from becoming authority.
Private scratch may be writable; the workspace and authority refs are not.
The mounted workspace itself is a startup resource/discovery input even when
the home is empty. Captured argv or a fixture that ignores workspace bait does
not prove real Pi ignores it: the exact Pi/build needs separate source review
and credential-free runtime witnesses for the fixed discovery restrictions.

Source supports the flag candidates, not a sealed effective inventory (paths
below are under `packages/coding-agent/src/` at the pinned commit):

- `main.ts:733-798` creates settings/services/resources before RPC; `939-951`
  starts a background model catalog refresh unless offline. RPC readiness
  cannot retroactively seal pre-initialization authority.
- `args.ts:318-343` documents the flags. `resource-loader.ts:513-586,680-785`
  still resolves packages and distinguishes discovery from explicitly supplied
  resources; `--no-extensions` is not permission to supply `-e` paths.
- `agent-session.ts:1538-1556` preserves an MCP exception for a plain tools
  allowlist; `--tools read` alone is not a complete callable-tool ceiling.
  `3288-3335,3525-3622` covers extension events/resources and registry filtering.
  Initial inventory and through-turn point-of-use restriction need separate
  witnesses, including terminal/drain time. Flags are not the I1 boundary.
- `model-runtime.ts:723-747,848-863` distinguishes model streaming from catalog
  refresh. Offline startup is not a provider-network ban. Kernel isolation
  supplies the fake profile's actual network denial.

Unresolved production facts are explicit: actual Pi runtime/artifact closure;
all startup helpers/package activity under the fixed inputs; reachable native
`read` semantics (including images/oversized files and non-workspace operands);
lifetime tool/resource/config closure; and the independently selected auth,
store and egress arrangement. A fixed controlled fixture must prove only its
own behavior; these unknowns cannot be filled with empty inventories. In
particular, observing a retry/compaction event and refusing afterward cannot
undo a model request: any future real profile needs a pre-use mechanical
restriction, not just this decoder's conservative refusal.

## Authentication alternatives — no live route selected

| Alternative | What this proposal selects or leaves open |
| --- | --- |
| Fake peer, no account | **Selected for the proposed credential-free design only.** Real READ workspace, no provider network/store/credentials, scripted protocol and analysis. Not Pi/provider qualification. |
| Pi-managed OAuth/subscription | Unselected and unqualified. An advertised login is not provider-supported eligibility or subscription permission. Pi is not automatically the unmodified vendor client covered by ADR 0021's exception. Need explicit supported provider/auth, custody/profile/route and fresh mode, refresh/expiry, egress and overage decisions; do not claim the route impossible. |
| API, including OpenRouter | Unselected. Would require an expressly approved credential-free-child provider route, deployment, credential custody and spend/limit policy, with independent conformance. No API/gateway fallback or paid cap is established here. |
| Local provider | Unselected. Need exact local endpoint/process ownership, capability/model fit, startup/egress and lifecycle/resource proofs, and an explicit auth/cost arrangement even if no subscription is involved. Not inherently free, isolated or qualified. |

API/local choices could eventually satisfy Pi's separate requirement; neither
can replace Claude/Codex subscription deliverables. No Codex operator budget,
authentication evidence or boot qualification transfers to Pi. Source helpers
`isUsingOAuth`/`isUsingSubscription` inspect snapshot/provider metadata; the
separate `getAuth` delegates to a resolver. Neither this source review nor an
RPC `get_state` response establishes the required provider-specific auth mode,
secret isolation, store refresh, expiry or overage enforcement.

## One dispatch: state at suspension and acceptance

These are local decoder/adapter facts, not a new durable state machine. The
provider is single-acquisition and the execution handle single-use; entry and
request budgets are spent **before** the first relevant await. Reentry poisons
completion, including when an earlier call is suspended. Damage, cancellation,
ownership loss and unsupported authority never reset to clean on a later event.

| Await/boundary | State that must already exist; state permitted on resume |
| --- | --- |
| Materialization/probe | Entry latched, complete recovery identity recorded, cleanup enrolled. Close before entry prevents entry without external work. Cancellation or ownership loss during startup cannot expose the executor; join partial startup before releasing custody. |
| Start conversation/read | One reader enrolled before any request. Buffer bounded complete **and partial** records; process arbitrary byte chunks and strict UTF-8/LF framing. No task dispatch merely because startup emitted an event. |
| Write correlated `get_state` | Mark this request spent before write; input budget includes interrupted prefixes, with no automatic retry. Match the outstanding response; require `model.provider="fixture"`, `model.id="pi-read"`, `thinkingLevel="off"`, `isStreaming=false`, `isCompacting=false`, `autoCompactionEnabled=false`, `messageCount=0`, `pendingMessageCount=0` for this fresh fixture. A response observed before its request is not accepted as fresh. Correlation is not client authorship or authentication proof; state does not attest pre-startup safety. |
| Write the sole `prompt` | Start observation first, mark dispatch spent before await and preserve possibly early lifecycle events. Do not require the acceptance response to precede final/settled events. Classify buffered events exactly once after disposition is known. A write interruption does not authorize another prompt. |
| Await disposition/events | Require `started`; `handled`/`queued` is unsupported, not successful analysis. A successful response is acceptance, not completion. Reject controller/UI/tool-authority requests outside the fixed profile; never answer an approval, extension UI, bash or model-change request to make progress. |
| Observe message/settlement | `message_end` completes one message, not the task. Permit bounded earlier user, assistant `toolUse` and `toolResult` message completions through the READ cycle described below. Require one terminal assistant analysis with `stopReason="stop"`, text content and no `ToolCall`, no unresolved/error READ calls, and explicit `agent_settled.aborted=false`. Neither a tool result nor `agent_end` is final analysis. Other terminal stop reasons (`length`, `deferred`, `error`, `aborted`) are non-success; `pending` is not a completed assistant message. Automatic retry/compaction/follow-up is outside this first profile and refuses rather than silently continuing. |
| Abort or terminal half-close | Cancellation revokes acceptance immediately. At most one bounded abort attempt may use remaining input/time; its response is not cleanup proof. A pending write is not overlapped with another write. Half-close after the terminal candidate; keep reading to actual EOF, accounting for trailing complete/partial records and diagnostics. |
| Exchange return/close | Callback return only proposes a result. Require EOF, clean supervisor and payload status, no timeout/overflow, empty stderr and joined owned teardown before success. Recheck run control. Close/reconcile retain guards until physical quiescence; cleanup failures escape, and caller cancellation propagates after joining. No raw PID recovery or conversation resurrection. |

`rpc.md:44-71` explicitly requires observing before prompt; this ordering case
is a future test obligation, not an observed Pi execution. Session events
generally lack a command ID. A fresh process plus one dispatch limits ambiguity
but does not turn session events into authentication evidence. The state fields
above exist in `modes/rpc/rpc-types.ts:96-109` and are populated at
`modes/rpc/rpc-mode.ts:443-463`; they observe selection, not the model actually
serving a request. Do not copy selected-model metadata into `served_model`.

The accepted vocabulary is finite: correlated command `response` records for
`get_state`, `prompt` and a possible `abort`; `agent_start`, `turn_start`,
`message_start`, `message_update`, `message_end`, `tool_execution_start`,
`tool_execution_update`, `tool_execution_end`, `turn_end`, `agent_end` and
`agent_settled`. Message roles are only `user`, `assistant` and `toolResult`.
Bounded assistant updates admit the text/thinking/toolcall start/delta/end
forms and the exported `start`/`done`/`error` forms in `docs/json.md:74-95`;
none replaces authoritative message completion, and errors latch non-success.
Unknown event/role/update forms refuse or mark damage, never silently vanish.

A normal positive READ cycle includes the submitted user message ending, an
assistant response ending with `stopReason="toolUse"`, a `read` tool lifecycle
and `toolResult` completion, then the terminal assistant analysis. Track each
bounded unique read-call ID/name across its completed tool-call declaration,
execution start/updates/end and matching tool result; reject duplicate IDs,
wrong names, unmatched/missing completions and either error indication.
The 128-record budget bounds the number of calls too; no separate unbounded
call inventory or claim about model-request counts/cost is introduced.
`turn_end` and `agent_end` copies must agree with completed observations and
cannot create another final result. These distinctions come from
`docs/json.md:31-109` and `docs/message-types.md:109-177`, not an executed peer.

Usage updates are cumulative **per assistant response**. Aggregate complete
finalized assistant `message_end` usage exactly once per response, including
intermediate tool-use responses; never sum streaming updates or repeated
`turn_end`/`agent_end` copies. Incomplete or incoherent accounting leaves usage
`None`, not zero or a fabricated complete total. This is the selected main
assistant-response usage scope, not nested tool/provider spend accounting.
Only an emitted, validated `responseModel` can supply served-model evidence;
the message's requested `model` and selected `get_state.model` cannot. If
responses do not identify one coherent served model, leave `served_model=None`.

Use a single absolute `grants.timeout_s` budget through probe, startup and
conversation; the first fixture uses 10 seconds for one small local read, not
as a production service-level promise. Joined cleanup may exceed that deadline;
it must finish or fail truthfully, never detach work to meet a wall-clock claim.

Proposed narrow fixture limits use existing `ProcessLimits` fields: input
64 KiB, stdout 1 MiB, record 64 KiB, stderr 16 KiB; unused artifact input retains
the existing 16 MiB default and is not an admitted task channel. These are
deliberately below current launch defaults (1 MiB / 32 MiB / 4 MiB / 64 KiB)
for a small READ analysis, not measured Pi requirements. Decoder additionally
allows at most 128 framed records, counting each before JSON decoding or
ignoring it. Check the byte ceiling before parsing; use bounded structural
validation to enforce JSON depth 32 before unrestricted recursive decoding.
Parse/structure errors are damage, never silently dropped. Bind every boundary
with a just-at/one-over input.

Published observations must also be finite: final `output` and `raw_reply`
each at most 16 KiB of JSON-encoded UTF-8, damage excerpt at most 1 KiB,
individual diagnostic/model strings at most 256 encoded bytes, and the entire
serialized outcome at most 64 KiB. Check the whole published object, including
every field/new field, not selected sites. Usage accepts bounded nonnegative
integer facts only (at most `2**63 - 1`); unreported usage, served model and
rate-limit/overage stay `None`. Do not infer spend, subscription status or zero
usage from silence.

Outcome mapping stays in the existing union: protocol damage demotes to
`ExecutorPartial` with bounded salvage; clean protocol/provider refusal or
failed clean termination is `ExecutorFailure(kind="exit")`; startup failure
uses `spawn`, timeout uses `timeout`, unsupported/unavailable profile uses
`unavailable`. No `protocol`/`cancelled` error kind is added. Cleanup failures
and caller cancellation are not converted into ordinary success outcomes.

## Finite proof checklist — proposed, not executed

Use the same adapter and decoder in portable and Linux tests. Substitute only
platform-bound primitives in portable tests. The peer is scripted, not a model;
its accepting response must depend on bytes actually read from a fixture file
in the admitted workspace, not a constant canned answer.

| Proof group | Affirmative positive witness | Refusal/fault witnesses | Evidence boundary |
| --- | --- | --- | --- |
| Contract/assembly | Exact READ/tool/network/model/effort profile plus required workspace executes one ordinary task; descriptor/profile/revision match. | Each incompatible posture, tools (including empty), network, inherited env, model/effort, missing workspace, unsupported task context/schema and drift refuses before spawn. No real provider is exposed. | Portable simulated provider/protocol. |
| READ and authority | Fake process reads a known workspace file, returns derived text, leaves content/Git ref unchanged; private scratch works. | Attempt workspace write, authority/host-home/sibling/store access, host env/FD use, network/DNS and descendant escape; positive attempted-action markers distinguish denial from an unexecuted test. | Linux physical boundary with harmless fake peer; not Pi native-tool or auth proof. |
| Startup/tool inputs | Assert exact argv/env/config and read-only mount selection; fresh session, fixed read-only tool and excluded discovery inputs. | Workspace AGENTS/config/package/MCP/extension bait does not become a fixture command; altered inputs/drift and pre-prompt model-work attempts refuse. | Portable checks prove supplied inputs and fixture behavior only. The workspace remains an input; exact Pi/build source and credential-free runtime startup/lifetime witnesses are separately required, not supplied by Linux fixture containment. |
| Wire accepting path | Fragmented UTF-8/LF JSONL; normal user-end, assistant-toolUse, READ execution/toolResult and terminal assistant-stop cycle; final+settled before acceptance response; finalized-response usage counted once despite update/end copies; clean EOF/status/stderr and exactly one dispatch. | ToolResult-only/text delta as final, missing tool/message end, duplicate/wrong read-call ID/name, unresolved/error call, non-stop final or settled-aborted; handled/queued, wrong/duplicate/pre-request response, unknown event/role/authority request, unsolicited/duplicate terminal, agent-end-only, missing final/settled, trailing malformed/partial record and retry/compaction/follow-up. | Portable scripted channel; source-shaped, not a recorded vendor transcript. |
| Bounds/public result | Small valid READ result and exact all-field outcome assertions. | Each input/record/count/depth/stdout/stderr/public-field/global cap binds at its boundary; duplicate JSON keys, nonfinite values and invalid Unicode refuse/demote. Warning with otherwise positive payload/status never succeeds. One assertion-killed mutant per accepting guard. | Portable; Linux additionally binds real pipe/input/output enforcement. |
| Await/cancel/drain | Successful one-read lifecycle positively records EOF, clean joined payload/supervisor and released guards. | Pause at every tabled await; cancel/reenter/close; fill a pipe while spawn or write is pending; early native EOF, abort loss, timeout, callback failure, repeated cancellation and cleanup failure. Observe joined handles/guards, not an empty fault list. | Portable doubles plus credential-free Linux process witnesses. |
| Durable lifecycle | Ordinary ControlPlane/RunHost task checkpoints, closes leases; restart uses checkpoint without another dispatch. | Literal driver death before/after dispatch and before checkpoint: positively witness death, successor fences/quiesces old acquisition before a fresh one; ownership loss cannot publish. Simulated counterfactuals retain simulated identity/disposition and no external execute/reconcile. | Portable journal/control evidence plus Linux owner-death/guard evidence; no exactly-once computation claim. |

No WRITE, capture, gate installation or autonomous contribution proof is added
by this READ slice. Existing merge effects remain the only installation route.
Each later real Pi/build/profile qualification must separately produce actual
startup/tool/resource, process, provider/auth/store/egress and mode/limit evidence;
fake or other-provider evidence cannot fill those cells.

## Source pins and review disposition

All upstream references above are under `packages/coding-agent/` at the single
commit pinned above. Exact reviewed blob OIDs are retained in #257; principal
sources are `src/main.ts` (`51df447c540ecb34a0c7ab9bf1edef1d337225a1`),
`src/core/agent-session.ts` (`8b330d555d0f45469fb291a2206217671d3977d5`),
`src/core/resource-loader.ts` (`3d59416af4c22974a6f176cecf621ba16860edc3`),
`src/modes/rpc/rpc-mode.ts` (`1c0995d36ec752155f1d13b019728f9343bb263c`),
`src/modes/rpc/jsonl.ts` (`8962c734021eee0d39d3a35ad8b5c020b0c2c14b`),
`src/core/model-runtime.ts` (`7c1dc820c29bc8ed2a0fe5f2f7fb68b3c22aebd6`),
and `docs/rpc.md` (`a39cc8da25c17e8d41af35bd32ac0bef5604b1b4`).
Message/usage selection additionally pins `docs/json.md`
(`ca76d632665d8878a4388437f8df0b6991e23365`) and `docs/message-types.md`
(`dfdafd5059635686f5b7f87b98f8d5ba1467a2be`).
Git blob OIDs identify inspected source, not installed executable conformance.

Rejected design shortcuts: no-tools text-only as READ acceptance; readiness as
a pre-startup seal; Pi OAuth marketing as provider permission; store+workspace
co-mount as inherited v3; acceptance/settlement/callback return as success; a
second process manager; paid/API fallback; and a fake pass as real availability.
These are design exclusions, not claims those upstream capabilities are absent.

Advisory review disposition: adopted the workspace-as-startup-input distinction
and separate real-Pi runtime versus Linux-fixture evidence. Rejected replacing
affirmative protocol completion with EOF/clean exit alone: clean termination
can occur without a successful task, while protocol completion without joined
clean termination is likewise insufficient. Both are load-bearing requirements.

This proposal is ready for design review. Acceptance and any subsequent bounded
implementation authorization are separate decisions; live routes remain
unselected and qualification order remains unchanged.
