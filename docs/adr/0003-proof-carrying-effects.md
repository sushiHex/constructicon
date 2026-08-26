# ADR 0003 — Proof-carrying effects: CheckResult → Attestation → EffectReceipt

**Decision.** One effect chain for every externally visible action. Evidence
(CheckResult, produced by gates and evaluators alike), authority (Attestation,
journal-minted, referenced by id, never caller-supplied), outcome
(EffectReceipt). Effects are at-least-once bounded by computed idempotency
keys; adapters declare native idempotency or reconcilability; recovery
reconciles before it ever re-executes an unknown.

**Merges.** Exact-merge-tree rule: gates run against the prepared merge commit
of candidate into the current base; `merge_verified(attestation_id)` installs
that exact commit or refuses when the base moved. The name "approve" is
reserved for human discretion (`ApprovalRecord`).

**Threat model, honestly.** Journal-minted proofs stop fabricated *data* — an
LLM-authored all-green result has no attestation id. They do not stop hostile
in-process Python; no in-process design can.
