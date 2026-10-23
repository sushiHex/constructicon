# Claude maintenance mismatch diagnostics

Bounded follow-up to [issue 40](https://github.com/sushiHex/constructicon/issues/40).
ADR 0021 and the accepted subscription-only maintenance rules remain authority.
This adds evidence, not a new authentication route or a weaker mode gate.

## Observed problem and hypothesis

The October 23 continuation passed fresh host and installation checks and
independent validation of the retained login lifecycle. Its observation then
refused with two initialization writes and `mode-mismatch`. The store was
preserved; the VM was parked and positively observed off. Reload, qualification
and READ did not run.

Under the pinned observer, a second write proves that the first reply matched
the exact allowed ambiguous first-party `Claude API` projection. It does not
prove that a second reply was classified: a failed second write or read can
retain the first verdict. It also cannot identify a second reply's predicate
if one was classified. The source audit in
[the maintenance design](M8-N6-subscription-maintenance-state-review.md)
explains a plausible cause: blocked profile lookup can leave subscription
metadata unknown, and ordinary refresh waits for natural eligibility. This is
a hypothesis, not a diagnosis of the discarded second response.

The retained Linux 2.1.296 member was independently rechecked without execution:
257,068,216 bytes, SHA-256
`24972e3bc859fab2b46ed4c1e51f7d6130f06d3bd550811a114640de3370d0de`.
Bounded source excerpts confirmed profile lookup at B@210350752, nullable
metadata at B@210472131, its `Claude API` projection at B@210446100, persistence
at B@210421729, and the ordinary refresh eligibility check at B@210437575.
Those source paths do not prove which path the live account took.

Repeating login or increasing a delay would not identify that cause. The next
observation must distinguish the mismatch without retaining account data.

## One classifier, unchanged acceptance

Classify a bounded initialization response once. Keep the existing public
`judge_initialize` verdicts and every acceptance/refusal rule unchanged; its
projection maps every account mismatch reason to `mode-mismatch`. Maintenance
may additionally retain one closed reason from the same classifier:

- `account-shape`
- `unsupported-account-field`
- `credential-source-present`
- `account-value-type`
- `provider-mismatch`
- `ambiguous-api`
- `subscription-mismatch`

Preserve the existing guard order. `ambiguous-api` means the exact existing
permitted ambiguity predicate, after envelope, correlation, version, idle,
pending-action, account-shape, field, type and provider checks. It remains a
refusal, never subscription evidence. Both supported selected plans retain
their accepting path; a different plan is not silently substituted.

The existing ambiguity predicate delegates to this classifier rather than
maintaining a second account policy. No raw value, unknown key, account
identifier, response digest, error text or credential crosses the diagnostic
boundary. A reason classifies a reply's reported shape; it does not attest
account truth, refresh completion, credential persistence or API-key use.

## State and compatibility

There is no new await, request, timer, retry or process owner. Verdict and
reason are replaced together when a response is classified, before the next
await. A later non-mismatch clears the reason. Until a response is classified,
the reason is unknown (`None`). A `classified_responses` counter starts at
zero and increments in the same synchronous classification step, not on a
write, UI frame or arrival. Its bound is the phase's request limit and it may
not exceed attempted writes. If a later write or read fails before its response
is classified, the fields still describe the earlier classified response.
When the count is known, a verdict exists exactly when the count is positive;
a reason requires a positive count and `mode-mismatch`. Historical constructor
compatibility uses an unknown count (`None`), never a fabricated zero.
Cancellation, buffered output, EOF and deadline checks retain their existing
precedence. Diagnostic state never permits another request or changes cleanup.

The observation record allows a closed reason only alongside `mode-mismatch`;
absence is unknown, not an inferred cause. Historical records are not enriched
from source inference. New maintenance evidence uses schema 2 because the old
external checker has a closed schema-1 shape. Old bytes and their checker stay
unchanged. Qualification's source-derived revision changes naturally; an old
qualification cannot authorize the modified controller.

## Proof and execution gates

Use synthetic responses to prove each category, precedence, both selected-plan
successes, malformed and non-mode refusals, reason clearing, the two-response
ambiguity path, and cancellation/write/read-failure semantics. Prove that two
attempted writes with one classification differ from two classified responses.
Walk every published
field and assert finite bounds; sentinel data must not appear on accepting or
refusing paths. Each new guard/classification needs an assertion-killed mutant.
Existing protocol and maintenance inventories remain required.

Review this state change before implementation, then independently review the
consequential classification and evidence changes. Require the full gate and
exact-head CI before merge. No test uses credentials or a vendor executable.

A live diagnostic additionally needs a reviewed updated checker and controller
installation, current custody, boot/drift checks and fresh paths. Preserve the
existing store; do not repeat login, force refresh, edit expiry or widen egress.
Use the original observation limits. Only a positive observation followed by
fresh-process reload and authenticated qualification can unlock the separately
admitted READ. An ambiguous result remains blocked; any other category directs
a specific offline investigation before another attempt.
