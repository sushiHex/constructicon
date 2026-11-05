# Merge reconciliation proof validation (issue #372)

Outcome: reconciliation verifies the same immutable request proof as execution
before inspecting or restoring an external installation marker. Risk tier:
consequential (proof acceptance and durable effect receipts).

## Confirmed premise

On baseline `b22581a`, a registered, cold-importable component in an ordinary
Graph called `ctx.effect("merge_verified", subject)` without an attestation.
The subject had previously been legitimately installed. The real walker
completed the new run successfully and published a committed receipt. The new
refusal assertion failed on that success. A separate reconciliation variant of
the existing forgery matrix also failed to refuse an invented attestation id.
The earlier temporary program that stopped at the `__main__` registration guard
was not execution evidence for this premise.

## Correction and compatibility

`MergeVerifiedEffect.reconcile` delegates to `_verified_subject` before calling
Git authority. This checks retained journal authority, action, exact subject,
world, successful checks, and immutable tree/parent integrity. It does not
require the live target still to equal the old baseline. ADR 0009's marker
therefore remains valid after a later target move. No Git authority code,
identity law, accepted plan, journal projection, or historical provenance is
changed. Missing or invalid historical authority is refused, never repaired or
minted by recovery.

The scope is proof validation, not removal of accepted identical-install
reconciliation: a valid request can still reconcile an installation made by an
identical racing actor. Installed Git state alone cannot replace its proof.

## Evidence and limits

Focused merge-effect and Git-authority tests passed (24 tests), including both
existing crash seams, the graph refusal, the expanded forgery matrix, and a
valid retry whose installed marker survives a forced target move. The matrix
covers invented, failing, wrong-subject, wrong-world and malformed-object proofs;
invalid requests leave receipts, markers and target unchanged. The graph test
also asserts the named missing-attestation failure, no successful effect event,
no receipt, and no new marker. Ruff and strict mypy on the changed adapter passed.

These are local, credential-free tests using temporary Git repositories. No
vendor, credential host or cloud runtime was invoked. Exact-head CI and
independent review remain delivery evidence to obtain; no full CI pass is claimed.
