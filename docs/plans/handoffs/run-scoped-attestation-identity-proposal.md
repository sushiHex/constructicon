# Run-scoped ordinary attestations and a closed v1 reader era

**Status: proposed; pending explicit owner acceptance.** Refs #371. This is a
decision proposal against `b22581a`, not an accepted ADR, implementation plan
authorization, or change to existing authority. Delivery is prose-tier; a later
implementation affects consequential durable authority. GitHub owns work state.

## Problem and decision boundary

`core/effect.py:attestation_id_for` hashes only `AttestationDraft`. Independent
leased runs can share a manifest and produce identical drafts. In
`_sqlite_execution.py:_stored_attestation_for_draft`, stored equality also binds
`created_by_run`; the second run therefore encounters `JournalDamaged` despite
valid independent evidence. Returning the first run's proof would instead
misattribute authority. This is a pre-existing identity defect, not permission
to weaken collision or creator-world checks.

The proposed successor preserves [I2 and I13](../../INVARIANTS.md), the fenced
minting and exact-subject law in [ADR 0009](../../adr/0009-git-authority.md), the
durable command law in [ADR 0012](../../adr/0012-durable-control-plane-and-mcp.md),
and positive, closed-era evidence in
[ADR 0016](../../adr/0016-positive-durable-facts-and-provenance-eras.md).
The [accepted M6.2 contract](../milestones/M6.2-internal-compression-rev2.md)
continues to permit one move per attestation and to refuse two different moves
racing from the same baseline. None of those accepted documents is edited here.

Owner acceptance must cover the identity law, the migration/read law, and the
retry and policy-conflict behavior below together. Acceptance of this proposal
must be recorded explicitly before implementation; issue tracking and a merged
proposal alone do not supply it.

## Proposed identity and API contract

Keep `AttestationDraft`, `Attestation`, `Journal.mint_attestation(lease, draft)`,
`mint_policy_attestation(draft)`, and `load_attestation(id)` wire/call shapes.
Creator identity remains derived from a fenced lease, never a draft field or
caller-selected replay flag. Keep the existing `att-` plus lowercase hex form.

| Path | Identity law |
| --- | --- |
| Existing helper and run-less policy | `attestation_id_for(draft)` remains exactly `att-` plus the hex of `digest("attestation", 1, draft.model_dump(mode="json"))` |
| New ordinary run-owned mint | New L0 helper `attestation_id_for_run(draft, run_id)` returns `att-` plus the hex of `digest("attestation", 2, {"draft": draft.model_dump(mode="json"), "created_by_run": str(run_id)})` |
| Existing persisted proof | Retain its exact ID, payload, timestamp, primary seal and all references |

The v2 body deliberately excludes time, worker ownership epoch, actor and
transport. A same-run retry remains the same proof across reclaim; two runs
with the same manifest and draft get distinct ordinary proofs. The draft's
subject, manifest, checks, check-set and evidence still participate unchanged.
No Graph, manifest, component identity, effect-key or command-plan hash law
changes. In particular, sealed promotion/rollback policy plans continue to
derive their predicted v1 IDs through the unchanged helper.

Minting still fences ownership and checks the run manifest and send subject
before looking up or inserting evidence. Same-run replay returns the exact
prior row before observing wall time; same-ID/different-content remains damage.
For an ordinary mint after upgrade, try its v2 identity first. If absent, a
v1 lookup may return only a positively witnessed historical row whose creator
is this run and whose entire draft matches. That is recovery of this run's
already minted fact, not new v1 minting. A valid v1 row owned by another run or
by policy does not block insertion of this run's v2 proof and is never returned
as its proof. Malformed selectors, missing sealed rows or contradictory content
must still refuse rather than be treated as absence.

Run-less policy minting remains v1-only and promotion-only. A rare pre-upgrade
run-owned v1 proof can already occupy the exact ID a later policy draft needs.
Preserving both that historical row and policy IDs makes a second insertion
impossible. Propose a named `ContractViolation` refusal
`policy_attestation_id_owned_by_history`, without mutation, when the fully
validated historical row has the same draft but a non-null creator. Do not
return it as a policy proof, relabel it, generate a replacement policy ID, or
misreport a valid cross-era conflict as journal corruption. Genuine inconsistent
same-ID content remains `JournalDamaged`. Owner acceptance must include this
bounded residual conflict; this proposal does not promise universal policy mint
availability over already occupied historical IDs.

## Proposed schema-10 migration and reader law

At this baseline SQLite is schema 9. Introduce schema 10 so older binaries
refuse before modifying a store containing the new identity law. Migration
does not rewrite proof rows or any promotion, effect, channel, event, checkpoint
or sealed command-plan reference. Fresh schema-10 stores mint only v2 ordinary
proofs and v1 policies.

Keep the current primary `attestation` and `legacy_attestation_m1_m2` families
and their exact hashes. Add one separate migration-only witness family,
`attestation_run_v1_pre_v10`, with key and selector both the retained ID. Its
domain-separated fact hash binds the exact attestation key and raw JSON bytes.
This is an additional era witness, not a replacement primary seal: moving an
existing row between primary families would invalidate immutable history.

The 9-to-10 rung takes `BEGIN IMMEDIATE`, rechecks version 9 under that lock,
validates the complete schema-9 inventory and existing creator-world relations,
and witnesses exactly the retained run-owned, content-derived v1 rows. It must
reject pre-existing future witness-family claims, malformed or ambiguous rows,
missing primary seals and unknown families. It validates the resulting
schema-10 inventory before publishing version 10 in the same transaction.
No `executescript` may implicitly commit that transaction. Errors and process
death before commit leave schema 9 and its logical facts unchanged; a concurrent
loser rereads and does no migration work. Older supported stores first climb
their existing rungs, with explicit pre-10 reader context, then pass this rung;
they cannot bypass its validation by being opened directly as current.

| Retained row shape | Schema-10 authority requirement |
| --- | --- |
| Exact M1/M2 shape | Existing M1/M2 identity, primary seal and historical restrictions, unchanged |
| Null creator, v1 content-derived ID | Existing policy law and primary `attestation` seal; no new witness |
| Non-null creator, v2 ID derived from that creator and draft | Primary `attestation` seal and current creator-world checks; no historical witness |
| Non-null creator, v1 content-derived ID | Primary `attestation` seal, exact `attestation_run_v1_pre_v10` witness, and the same creator-world checks |

Refuse a witness on policy, v2 or M1/M2 rows, mismatched witness bytes, orphan
witnesses, conflicting primary families, and a run-owned v1 row without its
witness. Current writes cannot create era witnesses. Current open/read/retry
never repairs seals or witnesses. The migration cannot infer an erased
historical fact whose row, seals and references are all absent; its claim is
limited to the validated retained inventory, as in ADR 0016.

## Canonical projection, selectors and inventory

Change the writer and all reader paths together. `_sqlite_attestations.py`
must distinguish syntactic identity classification from relational authority:
pure JSON decoding may recognize exact v1/v2/M1-M2 bytes, but cannot establish a
migration era without the connection and witness. Use explicit internal
provenance variants for policy-v1, run-v2 and witnessed run-v1 rather than
silently treating every run-owned v1 as current. `_fact_family` still chooses
the unchanged primary families; era witnesses have their own validation/count.

`require_attestation_seal`, `stored_attestation_for_id`, insertion and retry,
bulk inventories and dependent projections must use the same final authority
law. Extend creator-world enforcement to both run-owned identity eras.
In `_sqlite_registry.py`, audit the `content-derived` branch explicitly so
witnessed v1 and v2 retain exact modern promotion authority while M1/M2 cannot
authorize a new current move. Historical promotion exceptions stay confined to
their already witnessed historical relationships.

The JSON-only SQLite UDF `constructicon_attestation_id` must derive/recognize
both exact content-ID versions and preserve malformed-row detection. It is a
selector, not proof of a historical witness. Keep lookup of relational IDs,
derived IDs and invalid rows before declaring absence; then validate the
selected row and its seals through the connection-aware boundary. Apply the
same distinction to `_sqlite_runs.py` validity/creator UDFs and
`RUN_CHILD_ORPHAN_ANOMALY`, and the joined attestation projection in
`_sqlite_channels.py`. No SQL shortcut or direct JSON projector may grant an
unwitnessed v1 row authority that point lookup would refuse.

Extend the allowed family set, exact total-seal count, reverse inventory and
orphan checks in `_sqlite_schema.py` for one witness per qualifying historical
row. Preserve all existing primary-seal counts. An extra family cannot become
a tolerated count adjustment: every witness must match one exact qualifying
primary row. A canonical migration-only pre-10 projection must remain isolated
from current readers and writers. No deterministic JSON UDF may query mutable
connection state to decide era authority.

## Effect and promotion behavior

Creator/world, exact subject, checks, baseline and adapter guards remain in
force. Consumers still receive one typed `Attestation` by one string ID.
Independent proofs from runs A and B are not cross-run receipt replay. If A
promotes an edge, B's different proof for the same old baseline meets ordinary
stable-moved admission refusal; a retry using A's same attestation and exact
move returns A's existing receipt. Git reconciliation and installation laws
are not changed by this identity decision.

## Alternatives and review dispositions

The independent design review's collision premise matches the source hash and
full stored equality. Adopt its run-scoped v2 proposal and demand closed-era
readers, atomic migration and consumer coverage. Its squatting scenario is the
same namespace defect, not a separately established exploit. Preserve the
review's policy-ID warning as the explicit residual conflict above.

Reject returning another run's proof or ignoring `created_by_run` in equality:
both break provenance. Reject adding creator/actor fields to `AttestationDraft`:
that changes v1 and sealed plan bytes. Reject a composite database key: existing
references and public selectors carry one ID. Reject random IDs, caller replay
flags, and accepting both content-ID laws forever without witnesses: these
respectively lose deterministic replay, delegate authority, or make downgrade
indistinguishable from history. Reject rewriting old IDs or replacing their
primary seals. The additive witness differs from a replacement-era-family
sketch because immutable primary evidence must survive byte-for-byte.

## Required implementation evidence after acceptance

These are decision proof gates, not a second work ledger. Implementation must
show the accepting path and refusals through the real public journal/consumer
boundaries, with credential-free tests and relevant mutation proofs:

- Equal merge and promotion drafts from two valid runs sharing one manifest
  mint distinct v2 IDs with correct creators; both survive inventory and reopen.
  Policy and run mint ordering is independent for new rows. Same-run retries,
  including reclaim, return exact prior evidence without observing time.
- A genuine pre-upgrade writer fixture with v1 ordinary proofs, policy proofs
  and dependent promotions/effects/channels migrates without changing their
  bytes, IDs, references or primary seals. Same-run historical retry returns
  its witnessed v1 row; a different run mints v2. Cover the explicit historical
  policy-ID conflict and unchanged policy plan prediction/replay.
- Missing/extra/wrong witnesses, creator swaps, v1 injection after migration,
  valid-to-valid rewrites, erased primary facts and dual-family contradictions
  refuse consistently in point, bulk, selector-UDF, channel, run-world and open
  paths. Test actual old-binary refusal of schema 10 before durable writes.
- Interleave real constructors and inject death before/after migration commit
  and attestation commit. Prove atomic witnesses/version, rollback, no resealing
  on reopen, idempotent retry, ownership-loss and manifest-mismatch refusals.
- Prove one-attestation/one-move replay and two-independent-proof stable-moved
  refusal, including command fault seams. Mutants removing run ID from the v2
  hash or skipping witness/creator validation must fail by assertion.

Schema migration and authority implementation require consequential independent
review and the code gate under [WORK_TRACKING](../../WORK_TRACKING.md). This
document itself supplies no new runtime evidence or deployment authorization.
