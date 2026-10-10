# N5 WRITE: implementation state review

Living implementation review for [#156](https://github.com/sushiHex/constructicon/issues/156).
This does not amend the frozen [Stage 4 design](M8-N5-stage4-write.md).
The owner accepted its design with [clarifications](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6094163551)
and subsequently [completed READ and selected S4-6](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6101919423).
Vendor retry defaults remain within the fixed deadline; occurrence is unknown.
The shared N5 retry is unused. This document records design, not executed proof.

## Merged prerequisite

PR #147 merged as `88fc71d21d94c6897934ead65016b1d1857b184f`.
Its tree is byte-identical to reviewed head `449296e`. Inspection of that
merged tree confirms that terminal transitions refuse active acquisitions
under the journal fence. Cleanup attempts remaining siblings, relinquishes
failed local custody, and preserves ownership-loss precedence. An unresolved
close can leave a RUNNING, unowned run for recovery. A run status alone cannot
establish settlement. Historical terminal/active rows are not repaired.

## Smallest assembly

Keep the existing qualification entry and lifecycle. Add two importable graph
nodes, typed WRITE-only authorization pins, a concrete contained-resource
assembly shared with smoke, and a bounded projection of existing evidence.
There is no stage-plugin protocol, second scheduler or cleanup ledger.

Pins name workspace and gate capability id/revision, fixture identity and
base/target, and the report definition. Gate revision already names the check
set: do not store a redundant copy. Fixture identity binds reviewed seed
bytes and the canonical authority relationship; paths remain private. The
report revision covers its contract and complete projection/proof source,
not just one function whose imported helpers could change independently.

READ/no-dispatch authorization bytes retain their existing fields and
defaults. Only WRITE serializes the new pin block. The existing root-file
reader and its 8192-byte bound remain the authority boundary.
`codex.py` and `codex_protocol.py` remain unchanged.

## Resumption, latches and crash points

| Boundary | State already possible | Required observation and consequence |
| --- | --- | --- |
| Before constructing GitAuthority | Existing paths or aliases redirect constructor writes | Prove private canonical fixture custody, including hook and workspace destinations, before construction. No missing-file inference proves a seed. |
| Runtime-identification awaits | Target, fixture or runtime may have changed | Recheck actual fixture/base and revisions after probes and before registration or recovery. |
| Before RunHost startup | Journal may already contain a run and checkpoints | Prove dedicated run, fixed graph, inputs, bindings and assembly pins first. Startup is allowed to recover only this world. |
| Executor acquisition | An old attempt record may survive a reset journal | Existing exclusive reservation refuses reuse. Do not recreate, delete or reinterpret it. |
| Workspace materialization await | Executor reservation is durable; populate may fail | Preserve acquired-only evidence. It permits no automatic retry. Executor alias precedes workspace alias. |
| Before execute | Target may have moved since assembly | Compare sealed request/base with acquired workspace and actual target. Refuse observed drift before dispatch. |
| Native exchange/callback awaits | Intent may already be durable or turn write may have begun | Existing attempt law owns dispatch. Cancellation, timeout or an unknown result never refunds the attempt. |
| Capture await | Turn may be completed while no candidate exists | Preserve completed-turn evidence separately; capture failure is not WRITE success. Use the same writer grants. |
| Candidate publication before checkpoint | Immutable candidate exists but writer checkpoint is missing | A later acquisition still refuses the spent attempt. A candidate alone does not authorize writer replay. |
| Writer checkpoint before checker | Writer is complete; later owner epoch may recover | Restore through existing checkpoint validation. Checker-only recovery does not acquire or dispatch the writer. |
| Gate verify await | Target may drift; attestation may precede checker checkpoint | Require exact candidate, sealed expected base and tested tree. Attestation alone does not prove graph completion. |
| Node cleanup awaits | Checkpoint exists but close or durable row update may fail | Use merged #132 law. Preserve unresolved rows; report incomplete, never infer settlement from node output. |
| Observation timeout/error | Worker and cleanup may still be active | Join control shutdown before projection. Report incomplete; do not extend the wait or retry automatically. |
| Projection after shutdown | Rows may be missing, partial, inconsistent or recovered | Require positive matched attempt, validated checkpoint chain, journal attestation and all expected obligations. Empty collections are not success. |

The timeouts remain phase bounds, not a total session or cleanup deadline:
300 seconds for exchange/callbacks and writer capture grants; 30 seconds for
checker verification with a 20-second fixed check; 1200 seconds observation.
The existing runtime-identification/populate limits are retained. No limit
creates another model attempt.

## Evidence law

For success, materialize the completed run through the existing public API,
which validates retained checkpoint input hashes and component versions.
Then compare original checkpoint and journal evidence. Do not implement a
second checkpoint validator. A partial checkpoint may be described, not
certified as successfully restored.

Derive the writer logical lease from the authorized run, writer path and
executor binding; derive acquisition identity from that lease and the actual
recorded epoch. Match the attempt against these facts. Require the real
journal-minted attestation to bind that run/manifest, exact captured candidate,
sealed base, tested tree, checks and gate revision. Require all three expected
capability obligations, not merely `all()` over whichever rows happen to exist.

The public projection excludes model text, raw protocol/callbacks, refusal
details, account/store identifiers and local paths. Use typed finite statuses,
actual configured bounds and explicitly unknown observations. Use the existing
L4 detail byte ceiling for the entire report. Overflow must become a bounded
incomplete report with counts, never a silently truncated passing report.
No callback count, backend request count or vendor retry count is inferred.

## Smoke and proof obligations

Smoke has its own fixture and journal. It invokes the existing Linux launcher
with fixed worker argv and task input under the acquired workspace guard,
then real capture and the same fixed gate. It neither constructs a Codex
provider nor acquires an operator-store lock. Recheck the WRITE fixture after
smoke; smoke evidence is not authenticated callback evidence.

Test accepting and refusing paths from the first slice, including checkpoint
recovery with and without the writer checkpoint, target drift across awaits,
cleanup failure, missing/forged evidence and every public-field bound. Run
scripted native composition against the physical Linux worker, capture and
gate. Register assertion-only mutants once in CI. Existing credential-free
binary tests stay unchanged; new helper tests run no vendor binary.

The pre-implementation interface/state pass was inspected by a separate Sol
agent and the orchestrator against source. It is design review only, not
executed implementation or independent final-head review. Exact implementation
and runbook proofs remain future work until their results are recorded.

One final reviewed controller update will contain #147, #145 and WRITE.
The established reboot/requalification route requires a new generation.
No installation, smoke, WRITE turn or vendor conformance is claimed here.
