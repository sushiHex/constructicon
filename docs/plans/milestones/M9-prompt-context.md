# M9 â€” one prompt substitution through evaluation and promotion

Status: proposal for review. Not approved for implementation. Tracks [#45](https://github.com/sushiHex/constructicon/issues/45).
Baseline: `c518bd7`, bounded M8 closure. Start from the
[self-improvement design](../../designs/SELF_IMPROVEMENT.md) and [I12](../../INVARIANTS.md).

Prove one complete, credential-free learning loop. A trusted harness selects
evidence, an untrusted proposer chooses a candidate, a deterministic evaluator
decides whether it improves the held-out cases, and an independently authorized
promoter may move stable. No change to M8 executor or provider qualification.

## Use what exists

- Inspect the assembled component with `System.describe`, `describe_component`
  and `rdeps` (api/system.py). Inspect the actual manifest and grants before
  choosing the test fixture; the proof cannot use an invented registry surface.
- `ComponentDef` already pins its body and learning profile; lineage records
  parent and experience provenance separately (core/component.py).
  `TaskSpec` already accepts instruction and typed context (core/executor.py).
  The experiment changes one instruction choice; context remains empty.
  Several native profiles refuse nonempty context (codex.py:1707,
  claude_provider.py:602, pi_read.py:177 under substrate/executors).
- Use ControlPlane candidate registration, exact retained versions, and
  `runs_counterfactual` (api/control.py and api/_control_commands.py).
  Counterfactual pins the source world except the compatible override and
  simulates effects. It is an evaluation input, not a promotion receipt.
- Use journal-minted component attestations and the existing stable promotion
  and rollback commands (core/effect.py, core/journal.py, runtime/registry.py).
  Promotion checks the exact component, candidate and current baseline.
  The generic check does not establish that an M9 exam was independent.
- Existing run queries (api/_control_queries.py) are not per-case evidence
  grants. The proposer receives one fixed training projection, never a journal
  handle, a run-list capability, or a held-out artifact reference.

## One concrete experiment

Build one credential-free atomic diagnostic component with a typed output:
classification and evidence identifier. Trusted authors ship two reviewed,
importable implementations for the same component name. Each contains its
inline source-digested instruction and calls the same fixed task runner.
The candidate adds a requirement to cite the supplied evidence identifier.
Keep the port contract, required capabilities, runner, inputs and empty
context identical. Review the two source bodies to establish the only
semantic difference is that literal, then pin both source digests. The
binder accepts only the exact reviewed candidate definition and source
digest; reject every other version. The registry hashes the function source,
not its callees (runtime/registry.py:353-369). Seal the trusted fixture bundle,
runner and evaluator source, and scripted provider implementation/configuration
with the experiment. Recheck their digests and admitted provider revision at
evaluation and issuance. A changed helper or provider refuses even if both
component function digests still match. No generated Python, mutable module
globals, metadata prompt slots, free-form graph edits or new IR field.

Override only the atomic component name. Counterfactual resolution locks
every other source scope (api/_control_commands.py:151 and
runtime/_resolution.py:23-27); a composite-only override cannot substitute a
nested prompt reference. Check the resolved invocation version and a
credential-free provider observation that the exact changed instruction
reached the task seam. This finite trial proves the lifecycle and does not
qualify arbitrary prompt generation or context edits.

Before any candidate proposal, the curator pins a finite allowlist of
completed fixture run IDs, manifests, output checkpoints and artifact
digests. Materialize a bounded, content-addressed projection using an
explicit allowlist of fields. Retain the bounded canonical bytes in a
trusted journal checkpoint and verify their digest when read; an ArtifactRef
alone is not a byte store. Exclude secrets, raw transcripts and
unneeded identities. Deduplicate by case identity and input digest before
a deterministic, versioned, non-overlapping train/held-out split. Freeze
the split, redaction policy, expected labels, evidence identifiers and
score rule. Missing or corrupt evidence refuses; a stale or empty split
does not count as success. The proposer sees only train rows and the
finite approved prompt choices. The held-out bytes are held by trusted
evaluation assembly; the seal is an access boundary, not cryptography.

Use two counterfactuals of each retained source: one with no override,
one with the exact candidate override. Evaluate their paired results using the
same pinned input, task binding and evaluation rule. The candidate must
produce the correct label and evidence identifier on every case, with at
least one baseline failure corrected and no regression. A refusal,
missing/partial output, incompatible override or simulated effect mismatch
fails the exam. Reuse existing scripted task providers; no model judges or
live claims. Freeze the bounded downstream set from `rdeps` at the sealed
world. Require passing impact cases for every member, or fail closed if a
dependent lacks an impact case. Choose the first fixture with a small
nonempty downstream set.

## Authority and durable proof

Trusted assembly owns candidate validation and registration; the proposer
can suggest only a reviewed atom ID. The evaluator can read the fixed exam
and execute comparisons but cannot register, mint or promote. The proof
issuer rebuilds each paired evidence chain from the journal: the frozen
case and input digest, exact source run and manifest lock, expected override
map, durable simulated origin and discard disposition, terminal successful
status and complete checkpoint digest. Bind the scored output to that
checkpoint, not merely to an independently valid artifact. Reject swapped
cases, crossed pair members, unrelated runs and duplicate or missing
results. Verify simulated authority affirmatively; an empty effect list is
not proof. Recompute the score and impact results, then mint a run-bound
promotion attestation for the exact candidate and baseline. Use
a distinct trusted evaluation/issuance run. No production run-owned
promotion issuer exists today; use the fenced LeaseContext and contained
gate minting pattern as the reference (core/workspace.py and
substrate/gates/contained.py). Require the exact-subject owner approval
before minting, using the existing approval record pattern (sdk/std.py).
Never treat a simulated
candidate run's outcome or caller-written draft as promotion authority.
Do not expose the journal or generic policy mint to the proposer or
evaluator. If existing assembly cannot enforce this division, stop and
document the smallest missing authority seam before implementing it.

The promoter has the existing narrow registry grant and consumes only the
issued attestation after explicit owner approval of the exact edge. Verify
stable still names the attested baseline; stale evidence refuses. Use
existing idempotent commands and assert registration alone did not move
stable. Demonstrate one promotion, replay without a second mutation, then
rollback with expected stable pinned to the candidate and verify new
admissions use the old stable version while retained manifests keep their
pins. Existing registry offers stable, so no canary pointer, monitoring
scheduler or autonomy is proposed in this slice.

## Delivery and stopping rule

First deliver the credential-free fixture, case sealing and candidate diff
guard. Then compose evaluation, issuance, promotion and rollback with
positive and negative evidence: train/held-out overlap, changed fixture or
policy, unauthorized mint, missing result, stale baseline, changed helper or grant,
and retry after a durable boundary. Reuse existing crash and replay proofs
where the seam is unchanged; add only the missing composed proof. A
refused experiment leaves stable unchanged and records its reason. No
live vendor run, new registry/store, optimizer, or automatic promotion
is in scope. Implementation starts only after an explicit approval of
this reviewed plan.
