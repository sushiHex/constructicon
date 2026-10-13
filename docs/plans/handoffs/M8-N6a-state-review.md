# M8 N6a — Claude initialization codec state review

Design for [#168](https://github.com/sushiHex/constructicon/issues/168), a
bounded credential-free slice of [#40](https://github.com/sushiHex/constructicon/issues/40).
Authority remains ADR 0021 and M8 rev 3 N6. This is not a provider,
startup qualification, credential route, or availability publication. Frozen
Claude screen bytes remain unchanged; its older pin is not this slice's evidence.

## Current source pin, inspected without execution

Public registry metadata was read on 2026-10-13 UTC. The selected latest client
is **2.1.296**, paired with SDK **0.3.296**; stable is 2.1.287 and was not
substituted for latest. No installer script, native executable, login, model,
or vendor SDK was executed. Each downloaded tarball's SHA-512 was checked
against its registry `dist.integrity` before inspecting selected members.

| Public artifact | SHA-256 of downloaded tarball |
| --- | --- |
| [CLI wrapper 2.1.296](https://registry.npmjs.org/@anthropic-ai/claude-code/2.1.296) | `f6c375d51d4c22a7a850e185a0d7ddda85173f89dbbeb3262aa7971e3bd670b5` |
| [Linux x64 2.1.296](https://registry.npmjs.org/@anthropic-ai/claude-code-linux-x64/2.1.296) | `eef5a2e2b09a5e7d2ce784d1b3ba335ae7fc6c7f6256c802a0ebf2c21e4fd0e1` |
| [Agent SDK 0.3.296](https://registry.npmjs.org/@anthropic-ai/claude-agent-sdk/0.3.296) | `e966be99b6f047d56165e2ec03822f17a49beebd48ac8efb91dab1e48bcf69a7` |

The inspected Linux `package/claude` is 257068216 bytes, SHA-256
`24972e3bc859fab2b46ed4c1e51f7d6130f06d3bd550811a114640de3370d0de`.
SDK `sdk.d.ts` is 538514 bytes, SHA-256
`fc2866dfe2c01468edb19b1d94f26156bfacecdf1e7f1452b276ed2f8cc0b08f`;
`sdk.mjs` is 1239190 bytes, SHA-256
`5cf6f15237f9c84e6e5b724a10180478732457168921d7aa3e02632037cce299`.
SDK `manifest.json` identifies CLI 2.1.296, build
`fdb6c17a97b6e0e3cf15e3566663fca58e7c43a9`, and the same Linux size/digest.
This is source identity, not observed installed or running identity.

References below use zero-based byte offsets into those exact Linux/SDK MJS
members, or one-based lines in that exact SDK declaration file.

- SDK lines 4501ff and 5029ff define `control_request`, `request_id`, and
  `request: {subtype: "initialize"}`. Hooks, MCP configuration, prompts, skills
  and other initialization authority are optional; this slice sends none.
- SDK lines 384–430 and 5080ff define the success/error `control_response`
  envelope. At this pin initialize success includes both
  `pending_permission_requests` and `pending_user_dialog_requests`, possibly
  empty. Their contents may contain prompts and are never returned by this codec.
- SDK lines 23–33 define optional account fields and the provider enum.
  Native bytes 210449400ff (`xRe`) conditionally emit token/API-key sources;
  210446275ff map subscription plans to `Claude Pro` / `Claude Max`.
  Undefined properties disappear during JSON serialization; explicit `null`
  is not the declaration's absent optional field.
- Native bytes 233767919ff (`YL`) handle repeated initialize. Both its repeated
  and first branches call the response builder at 233772528 (`Vg`), which calls
  `xRe()` again and publishes the account projection and `session_state`.
  In contrast SDK MJS byte 1189034 (`accountInfo`) returns cached initialization
  account data. SDK lines 2994–3020 and MJS byte 1184863 document/implement the
  supported repeated initialize operation, including pending-request redelivery.
- Native byte 230397749 (`v7n`) still judges EndConversation eligibility using
  model eligibility, a flag defaulting false, and an anchored entrypoint regex
  whose default is `cli`. This is not proof that a particular launch excludes
  the tool, that flags cannot change, or that other internal tools are excluded.

## Smallest proposed implementation

Own `substrate/executors/claude_protocol.py`, its credential-free tests, and a
dedicated assertion-killed mutation inventory. Do not import Codex modules or
move their identity-bearing source. No L0 contract is needed for an inert
vendor-specific byte codec; tests are its genuine second consumer (I6).

Proposed API:

```python
class ClaudePlan(StrEnum):
    PRO = "Claude Pro"
    MAX = "Claude Max"

def initialize_request(request_id: str) -> bytes: ...

def judge_initialize(
    record: bytes, *, expected_request_id: str, selected_plan: ClaudePlan
) -> ClaudeInitializeVerdict: ...
```

`ClaudeInitializeVerdict` is one closed enum: `mode-match`, `record-invalid`,
`record-too-large`, `response-invalid`, `request-mismatch`, `initialize-error`,
`initialize-busy`, `mode-mismatch`. It publishes no wire fields. `mode-match`
means only that this one syntactically valid, correlated initialization reply
asserts the selected subscription mode. It never means startup or N6 passed.

The builder emits exactly one UTF-8 JSON record plus LF, with only the
documented request envelope and bare initialize subtype. Non-empty scalar
string ids are opaque correlation data, never actor identity; encoding and
the same record ceiling bound them. There is no user message or callback reply.
Invalid builder arguments raise only generic static exceptions, without input
representations. The decoder returns only the enum, retaining no raw wire data.

The decoder consumes one complete record, not an asynchronous stream. The
explicit adapter policy ceiling is 256 KiB including LF, independent of vendor
claims and below the existing launcher's 4 MiB ceiling. Reuse
`core.identity.parse_json_value` after strict UTF-8 decoding. Catch decoder
`ValueError`, `UnicodeError` and `RecursionError` into finite static verdicts;
do not expose their messages, offending keys, original record, or exception cause.
Reject embedded physical newlines/multiple records and malformed framing.

Require the exact control-response wrapper, success subtype, matching id, and
both pending arrays present and empty. A nonempty array yields
`initialize-busy`, without decoding or publishing its requests. Require the
reported version 2.1.296 and idle session state; these assertions cannot
authenticate a running artifact or prove no inherited prompt exists. Correlate
an error response's id before returning the finite error verdict; no raw vendor
error survives. Unknown envelope keys refuse on either response subtype. The
current native error wrapper may include `error_code` (native byte 213966719ff),
which is recognized, type-checked and discarded rather than published.

The initialization body is a bounded vendor metadata object, **not** a newly
invented full initialize schema. Inspect the fields above and `account`; do not
publish or judge the remaining catalog, permissions, hooks, settings or model
metadata. The account projection itself is closed to the pinned AccountInfo
field names; known present values must have their declared scalar types. Require
`apiProvider == "firstParty"`, `subscriptionType == selected_plan`, and complete
absence of `tokenSource` and `apiKeySource` keys (even explicit null refuses).
Email and organization, if present, are validated then discarded. The other
otherwise-supported subscription plan is a mismatch, not a fallback.

## Await/state analysis for the later driver, not implemented here

There is no await in this slice. Passing an expected id to a pure decoder
cannot prove who chose it, whether the reply predates its request, whether a
second reply was buffered, or whether it came from the sealed process.

A future driver must establish fresh process/non-resume custody, sole-reader
ownership, pre-request buffered/unsolicited-frame handling, host-owned request
correlation, one in-flight request, bounded write/read completion and cancellation,
and no model submission before every prerequisite is affirmatively complete.
Every resumed await must reconsider EOF, worker completion, abort, buffered
responses, pending callbacks and prior write uncertainty. No automatic retry
may turn an uncertain write into a duplicate request or dispatch.

Repeated initialize can mutate hooks/state and redeliver pending requests. Bare
requests avoid adding authority but do not make that operation inert. Empty
pending lists and idle state do **not** prove absence of an inherited prompt,
as the current SDK caveat explicitly says. Fresh mode projection does not prove
principal continuity, overage prohibition, physical isolation, startup catalog
closure or account truthfulness. Those remain unavailable pending independent
Claude startup/layout/tool/egress/conversation evidence; no Codex credit transfers.

The eventual executor should reuse existing TaskSpec, EffectiveGrants,
ExecutorOutcome, lease lifecycle, ProcessIO and launcher contracts. This slice
adds neither a provider nor a second scheduler, session manager or telemetry
framework. Full record collection and task lifecycle await a bounded follow-up.

## Verification acceptance before publication

Prove both selected-plan permitting cases and wrong selected-plan refusals,
alternate providers, unknown account fields, auth-source presence/null, omitted
required facts, wrong ids/types/subtypes, pending-list absence/nonempty states,
version/state mismatch, malformed UTF-8/JSON, duplicates/nonfinite/invalid Unicode,
deep recursion and multiple frames. Bind the byte ceiling with at-limit and
over-limit inputs. Sentinel account/error/prompt fields must never appear in
published verdicts or decoder errors. Assert the builder has no extra authority.

Each new guard gets a measured assertion-killed mutant in the dedicated inventory,
registered once in the existing CI matrix. No vendor executable, SDK import,
credentials or network is used by these tests. Exact-head verification and
independent review are required before claiming this bounded slice complete.
