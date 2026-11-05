# 0023 — Ordinary attestations bind their minting run

**Status:** accepted, 2026-11-05. The owner directed adoption and implementation
of [#371](https://github.com/sushiHex/constructicon/issues/371) in the approved
four-part delivery wave. This is an additive decision; older accepted ADR and
plan bytes remain unchanged.

## Decision

Independent valid runs may produce equal attestation drafts. Their proofs must
remain independently attributable. New ordinary attestations use
`digest("attestation", 2, {"draft": draft.model_dump(mode="json"),
"created_by_run": str(run_id)})`, retaining the existing `att-` hex form.
The fenced lease supplies the run identity; no
caller-provided creator, timestamp, ownership epoch or transport enters it.

The existing v1 helper and run-less policy identities remain unchanged. Draft,
attestation and public journal call shapes are unchanged. Existing proof IDs,
payloads, timestamps, references and primary seals remain byte-for-byte intact.

Schema 10 closes the earlier ordinary-v1 writer era. Migration holds the write
transaction, rechecks its version, validates the complete old inventory, and
adds exactly one `attestation_run_v1_pre_v10` witness for each retained ordinary
v1 proof. Its domain-separated hash binds the exact key and raw bytes. Validate
the resulting inventory before publishing the version and committing. Existing
primary families are neither replaced nor resealed.

Current readers require that exact witness for ordinary-v1 authority, and the
existing creator-world checks for either ordinary identity version. Policy-v1
and exact M1/M2 rows retain their distinct existing laws. Witnesses on other row
kinds, missing/contradictory witnesses and orphan seals refuse. Current writes
cannot mint historical witnesses. Migration compatibility is confined to the
exact connection and held pre-10 transaction and ends before strict current
validation; it cannot become ambient reader authority.

Same-run retry returns its existing exact proof before observing wall time,
including a positively witnessed historical v1 row. A valid proof belonging to
another run is never returned as this run's proof. A policy v1 ID already owned
by a valid historical ordinary proof refuses without mutation as
`policy_attestation_id_owned_by_history`. This residual conflict is accepted;
it is neither journal corruption nor permission to rewrite history.

One attestation still authorizes one move. Independent proofs racing from the
same old baseline meet the existing stable-moved rule; receipt replay remains
historical. No effect, command-plan, manifest or component identity law changes.

## Rationale and evidence obligations

The [preserved proposal](../plans/handoffs/run-scoped-attestation-identity-proposal.md)
owns the detailed alternatives and implementation proof obligations. Its
pre-acceptance status text is historical. Returning another run's proof,
weakening creator equality, random identities, rewriting old IDs and accepting
unwitnessed v1 rows are rejected because they lose provenance or replay truth.

Implementation must prove independent minting, exact retries, genuine old-writer
migration, old-reader refusal, all reader/selector/consumer paths, atomic crash
and concurrency behavior, and assertion-killed distinct guards. Acceptance is
design authority; it is not a claim that those implementation proofs have run.
