# Validation and proof hardening delivery record

Refs #367, #368, #369, #370 and #372. This record explains one coherent correction
wave, not a new plan or task ledger. GitHub issues own work status. Accepted plans,
ADRs and existing provider/host authorizations are unchanged.

## Behavior established

- Authored connection cycles are rejected before upstream closure can truncate a
  back-edge. Endpoint defects still win. Inline, retained and Loop-body graphs use
  the same admission path; explicit Loop feedback remains legal. Empty NodeId
  syntax is unchanged. Public cycle paths are bounded previews with original
  totals and truncation flags, including the framed diagnostic.
- Early SQLite migration rungs reread user_version under the held write lock.
  Statement-by-statement DDL replaces implicit-commit executescript calls, so
  schema changes, backfill and version publication remain in one transaction.
  Stale constructors do not downgrade a current store. Malformed history still
  refuses; current open never repairs it.
- Legacy gate snapshots compare exported paths, file types, blob identities and
  supported modes against the exact Git tree before checks can attest it. Lossy
  archive attributes refuse and remove the export. Windows regular-file modes
  are normalized consistently; POSIX executable-bit checks remain active.
- CheckResult derives agreement from Boolean coercion without replacing the raw
  supplied field, preserving strict-call refusal and legacy lax compatibility.
  Caller dictionaries are not mutated.
- Merge reconciliation applies the same immutable proof checks as execution
  before recovering or writing an install marker. A valid committed proof still
  recovers after the target moves; current target movement is not confused with
  loss of the earlier authorized installation.

The walker does not acquire a new decision. No provider, sandbox policy, workflow,
credential, private-host action or live model run was changed or invoked.

## Evidence and independent review

The four initial candidates were reviewed separately and assembled at tree
dc6266d10069ccf1f8e9262333f782009c02afb7. The combined cloud review verified that
exact tree and reported 122 composed focused tests passing. These are reviewed
candidate receipts, not final-head CI evidence.

Local independent checks reproduced and corrected three introduced candidate
defects: strict Boolean normalization before outer validation, Windows suffix-
derived executable bits, and cycle evidence escaping its detail cap. Narrow
follow-up reviews passed. Observed local checks included 55 CheckResult cases;
12 migration atomicity cases and four v0/v2 compatibility cases; the ordinary
Windows .cmd snapshot acceptance case; and 40 cycle/endpoint cases.

The additional merge-reconciliation correction was independently reproduced
through a cold-importable normal graph/walker call. Its refusing test observes
the exact missing-proof failure and no committed receipt or marker; legitimate
recovery after target movement and existing crash seams passed. Independent
source/test review found no blocker. The scoped gate test now also asserts the
exact snapshot mismatch at the gate node, so unrelated early failures do not
satisfy the composed regression.

Seven targeted mutants passed their baselines and were killed by assertion:
cycle-check removal, cycle-preview bound removal, stale migration guard removal,
premature migration transaction commit, legacy export equality removal, raw
Boolean truthiness, and reconciliation proof-check removal. They live in the
existing fault-coordinate, capability-provenance and gate inventories, with no
new workflow or test-selection framework. A first scratch invocation via stdin
could not launch mutation children and proved nothing; it was replaced by an
actual runner file before reporting any kills.

The final-head full CI and review receipts belong in the delivery PR. The full
local suite is not duplicated after every edit under WORK_TRACKING's delivery
policy; focused checks exercise each changed behavior and the required CI covers
the final candidate broadly.

## Review dispositions and practical limits

A Windows host unable to materialize an exact symlink may now refuse a legacy
snapshot. This is intentional fail-closed evidence behavior: accepting a copied
target would reintroduce the false tested-tree guarantee. The message explicitly
includes lossy export; same-UID mutation containment remains the legacy limit.
Submodules refuse as unsupported entries, matching contained snapshots.

A hypothetical persisted contradictory CheckResult does not establish a new
reader regression: the old decoder already refused explicitly inconsistent
Boolean status/ok bytes. No previously decodable historical row was reproduced.
Invalid type coercion is not a historical authority era.

Migration constructor interleavings directly cover versions 2 through 5; version
0 has stale-step and compatibility checks rather than a constructor-race fixture.
That limitation remains explicit. No new physical confinement claim follows from
portable tests, and Windows mode checks are not POSIX execution evidence.

The ordinary cross-run attestation collision is separately tracked in #371 with
a proposed reader-era decision; it is not repaired by dropping creator provenance.
Recurring rollback outcomes remain explicitly tracked in #373 against accepted
transport-neutral policy identity. Broader replay-by-attestation and retained
predecessor rollback are intentional semantics, not additional defects to remove.
