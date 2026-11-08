# Real-answer comparison: preparation and decision packet

This prepares the next evidence question after the
[bounded live selector lifecycle](M9-live-selector-record.md). It does not
report a quality result or authorize a host session, model call or promotion.
The owner authorized preparation in the productization wave tracked by
[#389](https://github.com/sushiHex/constructicon/issues/389).

## Question and treatment

Does adding `Cite the supplied evidence ID.` improve the existing diagnostic
task on a small independent set? The baseline is `Classify the observation as
network or storage.` Both instructions come from
[`api/_m9/fixture.py`](../../../src/constructicon/api/_m9/fixture.py).
The fixture deliberately accepts only its scripted executor; leave that guard
intact. A future live assembly needs its own reviewed implementation using the
existing task-shaped executor contract.

The [earlier proposal](https://github.com/sushiHex/constructicon/issues/45#issuecomment-6670757042)
owns the proposed experiment, not the completed M9 acceptance claim. This
packet makes its preparation dependencies and decision boundary explicit.
The experiment remains a proposal; preparation approval does not approve its
implementation or execution.
The accepted M9 plan and historical artifacts remain unchanged.

## Freeze before dispatch

| Input | Required retained fact |
| --- | --- |
| Exam | Independent curator supplies exactly four synthetic cases, two network and two storage, with unique IDs and expected labels; no selector training/scripted-exam overlap or prior tuning exposure |
| Provenance | Curator identity/role, case source, redaction and deduplication check, canonical bytes and SHA-256; an exposed or unverifiably independent case requires a new exam before approval |
| Treatment | Exact baseline and citation instruction, empty context, identical shared JSON-format instruction and strict parser; the shared format permits `evidence_id: null` and never demands citation |
| Execution | Reviewed assembly/component/helper bytes, both manifests, exact case inputs, grants, qualified provider/model/configuration and generation |
| Scoring | Versioned deterministic scorer, fixed expected labels/IDs, immutable output and provenance rules, and exploratory success rule below |
| Order | Canonical sorted case IDs; baseline then candidate at odd positions, candidate then baseline at even positions; eight serial application dispatches, no retries |
| Exposure | Exact package/exam digests, per-attempt deadline and byte limits, total dispatch limit and explicit owner-selected subscription/overage terms |

The proposer receives only the existing training projection and fixed catalog.
It receives neither held-out rows nor answers nor a journal handle. Exam
sealing is an authority/provenance boundary, not a claim of secrecy from the
trusted operator. Do not copy public fixture cases into a supposedly new exam.
The earlier proposal records a private four-row candidate digest; it still
needs independent review and sealing before use. This preparation neither
adopts those rows as an independent exam nor fabricates future qualification
pins.

## Retain, score, decide

Each answer must bind to its run, case/input digest, arm, manifest, terminal
checkpoint and exact retained output bytes. Parse one bounded JSON object with
no duplicate keys into the existing strict `Diagnosis` contract. A pass needs
both the expected `network`/`storage` label and the supplied evidence ID, with
no normalization or model judge. Missing, malformed, refused, partial or timed
out answers fail their case. Preserve the reason; never substitute an answer.

Reject crossed, duplicate, altered or missing evidence. Incomplete dispatch or
unverifiable provenance makes the overall trial **inconclusive**, even though
individual failed answers remain failures. Publish all four paired outcomes,
both pass counts and the actual order/timestamps. Exploratory improvement
requires candidate 4/4, baseline at most 3/4, and no baseline-pass/candidate-fail
pair. Otherwise report **no demonstrated improvement**. No replacement cases,
selection changes, retries or threshold adjustment after observing outputs.
Four pairs with one draw per arm cannot establish general model improvement.

Both arms must have equal inputs, output contracts, limits and isolated state;
verify the actual delivered instruction against its pinned treatment, not just
the requested component name. These would be normal live READ runs.
`runs_counterfactual` must simulate and
cannot be used to disguise actual dispatch as simulation. This result cannot
mint a promotion proof: independent approval, exact baseline, frozen `rdeps`
impact coverage, simulated evidence and issuer requirements remain separate.

## Readiness and stop boundary

Preparation is complete when the fixed protocol and its missing inputs are
explicit; **execution is not ready** until an independent exam is frozen, the
minimal live assembly/parser is reviewed and fake-tested, and a separate exact
execution/cost decision names current qualified pins. Fake tests of the actual
proposed entry must cover all eight accepting runs, mismatched pins,
altered/crossed results, partial output, limits and interruptions at each durable
boundary, including restored-state restart. A committed or uncertain attempt
must never dispatch again; selection/evaluation must never mint or promote.
Independent review must cover actual task matching, authority and evidence
binding. The preceding M9 READ
and promotion approvals authorize none of these eight calls.

Token usage is observational. Backend request count and monetary cost may be
unknown; eight application dispatches do not impose a finite monetary ceiling.
Select exactly one route: subscription exposure needs explicit owner acceptance;
an API route needs separately approved compatible qualification, verified pricing
and an enforceable monetary cap. Neither route is authorized here.
Use [ADR 0024](../../adr/0024-retain-native-executor-metering.md) observations
when available, without inventing prices or importing historical transcripts.
Fresh custody, installation and qualification must be positively established;
historical success establishes no current availability. Stop the whole
experiment on any refusal, timeout, uncertain dispatch, lost response, drift,
missing evidence, exhausted limit or cleanup failure. Preserve evidence and
known/unknown exposure, complete required withdrawal and park/custody release,
and never retry under a new identity. Replay may retrieve evidence only. A new
experiment needs a separately reviewed protocol and explicit new authorization.
No live action is part of this packet.
