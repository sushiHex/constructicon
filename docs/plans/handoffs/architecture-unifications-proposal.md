# Six unifications: fold the live path back into the kernel

Status: review draft, 2026-11-12, written against `main` at `c9f0c84`.
A proposed direction. It authorizes no implementation, installation, host
operation or model attempt, and it changes no invariant or accepted ADR.
Each unification needs its own reviewed change, and those marked below need an
owner decision or an ADR first.

Refs [#407](https://github.com/sushiHex/constructicon/issues/407).

## How to read the evidence

Every `file:line` below was read at `c9f0c84`. Paths are relative to
`src/constructicon/` unless they start with `tests/`, `docs/` or `scripts/`.
A statement marked *(inferred)* was not confirmed at source. The
[open questions](#open-questions) list what five review passes could not
verify; nothing there should be read as a fact.

## Diagnosis

The kernel is small and still coherent: one graph IR, one sealed manifest per
run, leased capabilities, journal-minted attestations, idempotent effects with
receipts, and one command law.

M8 and M9 reuse that kernel for execution. A maintenance attempt is a real
Graph started through `runs_start`, and its acceptance is a journal-minted
attestation. Around that run they built a second system: a second kind of
authority, a second ledger, a second vocabulary for refusal, and identity
derived from files rather than from meaning. Each is a special case of a
kernel idea that was rebuilt beside it.

Two consequences are visible today:

- **A wording change costs a release.** The generation-18 attempt was refused
  because of instruction wording
  ([outcome record](https://github.com/sushiHex/constructicon/issues/77#issuecomment-6785983613)).
  Correcting the wording changes an application revision and the installed
  controller tree, so the next attempt needs a new package, an installation and
  new authorizations.
- **The central promise is not exercised by a live contribution.** The
  maintenance Graph "never installs its candidate"
  (`api/plan_manifest_application.py:1`). `merge_verified` is assembled only in
  `api/system.py:142`. The q13 result reached the repository as an ordinary
  pull request (`README.md`, M8 section).

## The six unifications

Each row folds a parallel mechanism into one idea. None loosens a guard: every
proposal keeps exactness and attestation, and either narrows what a pin covers
or moves a fact to the place that already holds facts of its kind.

| # | One... | Folds into | Retires |
| --- | --- | --- | --- |
| 1 | identity per meaning | content identity (ADR 0006) | whole-file revisions; the instruction hashed three times and shown nowhere |
| 2 | permit | the capability lease law | two authorization types with copied predicates |
| 3 | refusal code | the sealed `NodeFailed` event | exception prose as the wire format |
| 4 | model seat | the executor seam (ADR 0005) | all-or-nothing model realness in tests |
| 5 | ledger | the journal (ADR 0007, ADR 0024) | the attempt file and the dedicated journal |
| 6 | path | `merge_verified` | the hand-made pull request |

### 1. One identity per meaning

**Today.** A pinned revision is the hash of a whole source file:

- `PROTOCOL_REVISION` hashes all of `codex_protocol`
  (`substrate/executors/codex.py:240`), tool description included.
- `ADAPTER_REVISION` hashes all of `codex.py` (`codex.py:2619-2620`).
- The launcher revision hashes all of `linux.py`
  (`substrate/executors/linux.py:626`).
- The maintenance application revision hashes eight whole files
  (`api/_maintenance_identity.py:11-19`).
- The same application file is hashed again as the writer's and checker's
  adapter revision (`api/plan_manifest_application.py:263`).

The kernel's own law revisions already use the right grain: they hash named
members, not files (`core/executor.py:256`, `core/native_operator.py:273`).

The file boundary is therefore the qualification boundary. Splitting or sharing
a file moves a pin, which is why the Claude lane imports `EvidenceFile` and
`_fsync_directory` from the Codex lane and hashes them symbol by symbol
(`substrate/executors/claude_lane.py:59`, `:114-119`).

The instruction has no identity of its own. It is not a field of either request
model (`core/maintenance.py`), and the approval preview is the authorization
dump (`api/maintenance_entry.py:367-372`). The owner approves a digest over
eight files and never sees a digest of the words the model will read.

**Proposal, in two halves.**

- *Instruction as bound data.* Add the instruction's SHA-256 to the request
  the owner approves. Ship the bytes beside the reviewed bundle and hash-check
  them at assembly. The request is already inside the root-custody
  authorization, so exactness becomes explicit and visible.
- *Declared revision units.* Give each pinned concern a small module and hash
  a declared list of them, in the style the law revisions already use.

**Guarantee preserved.** Every byte that decides admission or acceptance stays
hashed. The exam is untouched, so a wrong instruction can cost an attempt but
cannot produce a false acceptance: the gate still decides (I12).

**Needs an owner decision.** Source currently says the instruction is "never a
caller-selected instruction or exam" (`core/maintenance.py:32`,
`api/plan_manifest_application.py:8-10`). The first half restates that as
"owner-approved by digest". The channel instruction also interpolates the
oracle's helper source, so a data copy needs a parity check against it.

**Cost.** Instruction half: medium, and it needs one last controller
installation. Unit half: large, with one deliberate requalification per vendor.

### 2. One permit

**Today.** Two authorization types carry the same idea, a root-custody permit
for exactly one run:

- `acquisition_faults` is the same ten-row predicate in both, differing only
  in the epoch bound and the refusal prefix (`core/qualification.py:156-174`,
  `core/maintenance.py:170-190`).
- The bounded WRITE grant shape is written out twice
  (`core/qualification.py:109-118`, `core/maintenance.py:145-154`).
- Both are read through one root-custody primitive, "shared by the separate
  authorizations" (`substrate/executors/qualification.py:40-71`).
- Admission clears a provider's published unavailability only for a provider
  holding such an authorization for exactly this graph
  (`runtime/validator.py:338-361`).

**Proposal.** One L0 run permit with a typed purpose and payload. The two
existing types become two purposes of it, with byte-identical wire goldens.

**Guarantee preserved.** Root-file custody; exact run, path, binding, graph,
capability, revision, operator binding, grants, epoch and expiry pins; timeless
admission.

**Cost.** Medium. It touches no vendor revision *(inferred: both types live in
`core/`, outside the adapter modules; the application revision does include
`core/maintenance.py`)*.

### 3. One refusal code

**Today.** `core/errors.py:1` says "One error taxonomy, deliberately small".
A specific cause is computed at its producer and then travels as English:

- The walker records a failed node as `str(exc)` and the exception's type name
  (`runtime/walker.py:1831-1835`).
- The maintenance diagnostic recovers the cause by exact-matching eleven
  sentences (`substrate/journal/maintenance_diagnostic.py:67-79`, `:298-304`).
- One name covers several causes. A captured candidate equal to the base is
  `capture-unchanged` whether the model made no call, only read, or rewrote
  the file unchanged (`api/plan_manifest_application.py:153-154`;
  `tests/api/test_channel_reply_hostile_replies.py` pins the three).
- Any callback fault becomes "the contained callback failed" with a type name
  (`substrate/executors/codex.py:966`).
- The gate's refusal already carries "a closed reason code; never
  candidate-controlled diagnostic text" (`substrate/gates/channel_reply.py:55`),
  and a failed gate is then reported as one sentence
  (`api/plan_manifest_application.py:186-190`).

**Proposal.** One closed cause code, carried beside the prose from producer to
report: an attribute on the violation, a field of the `NodeFailed` payload,
and a projected field of the report. The sentence table becomes the fallback
for records written before the code existed.

**Guarantee preserved.** Codes are drawn from closed sets and carry no
model-authored content, so the "digests and lengths, never text" bound holds.
Sealed events and report readers pin exact shapes, so this lands as a new
schema era beside the old one (ADR 0016), never as a widened old record.

**Cost.** Medium. Whether a new `CheckResult` field needs an era of its own is
an [open question](#open-questions).

### 4. One model seat

**Today.** The model's decision is tested at two seats that never meet:

- A scripted native peer sits below the vendor binary and drives the real
  adapter, worker, capture and gate (`tests/maintenance_task_world.py:184-194`,
  `tests/api/test_channel_reply_hostile_replies.py:249-258`).
- A fake provider sits above the real binary. It answers with at most one tool
  call, and nothing stands behind it (`tests/native_provider.py:85-97`).

A live attempt is the only place every part meets. It retains counts and
categories of callbacks, never their content
(`core/qualification_write.py:160-172`).

**Proposal.** Name the seat that the hostile-reply harness already has, and
give it four occupants: ideal script, hostile script, recorded replay, live.
A replay must check each tool output against the recorded digest and fail on
divergence.

**Guarantee preserved.** Test-only. No product guard changes.

**Needs an owner decision.** Replay needs the model's programs and reply as
bytes, held privately. Digests and lengths classify a failure but cannot replay
it. That is a private-output policy choice.

**Cost.** Small for the seat. Retention is a separate change.

### 5. One ledger

**Today.** Two records of intent are written before one dispatch:

- the journal's metering intent, `meter.intend()`
  (`substrate/executors/codex.py:1758`, ADR 0024);
- the attempt file's intent, `self.attempt.intend()` (`codex.py:1773`).

The attempt file exists because the budget must "outlive a journal reset". It
is "not an executor ledger (ADR 0018:331-332), which the owner set aside for
this one artifact" (`substrate/executors/attempt_record.py:1-17`). No ADR
records that exception.

The reset it guards against comes from a second rule: a maintenance run needs
a journal that holds no other component and no other run
(`api/maintenance_entry.py:219-224`).

**Proposal.** The journal becomes the only attempt budget: it records that a
permit was consumed. Live runs then use the standing journal, with the
"nothing else" rule replaced by a check scoped to the permit and its manifest.

**Guarantee preserved.** One attempt per permit; intent before the first
native write; a possibly dispatched attempt is never retried.

**Needs an ADR.** This changes the live path and retires a recorded owner
exception. It rests on an [unproven premise](#open-questions): that a journal
row is as strong as the file against the stated threat model.

**Cost.** Large. It depends on 2.

### 6. One path

**Today.** The maintenance Graph is writer then checker. Acceptance "does not
claim installation, merge, or durable rendered-artifact storage"
(`core/maintenance.py:44-48`).

**Proposal.** End the fixed Graph in `merge_verified` against the private
authority. Export becomes a projection bound to the effect receipt.

**Guarantee preserved.** The exact prepared merge commit, the moved-base
refusal, and the one-parent history proof.

**Cost.** Small to medium. It is the last step because it changes what a live
window does.

## Sequence

| When | What | Why then |
| --- | --- | --- |
| Before generation 19 | The instruction half of 1 | Generation 19 already needs an installation; this makes it the last one caused by wording |
| MVP window | One live attempt under its own scope and approval | #407 |
| After, with no requalification | 2, 3, 4 | None touches a vendor revision *(inferred for 3: the callback refusal sits in `codex.py`, which is pinned)* |
| One planned requalification | The unit half of 1 | Every later split and the shared native-operator lifecycle wait on it |
| Last | 5, then 6 | They change the live path itself |

## Open questions

Carried from the reviews. None is established.

- Whether a revision change forces a live requalification in every case, or
  only a new authorization. The reviews inferred it from the digests and ADR
  titles.
- Whether a component's content hash includes its `source_digest`, as the
  double hashing in unification 1 assumes.
- Whether the workflow file's full digest, or only values derived from it,
  enters host identity.
- Whether adding a field to `CheckResult` changes sealed attestation bytes and
  so needs an ADR 0016 era.
- Whether a journal row is as strong as the attempt file. The file's own
  threat model says "the runtime is not an adversary of its own budget"
  (`attempt_record.py:15-17`).
- Whether operator packages already built enforce exact key sets that a new
  report field would break.
- What the capture does when a write lands only on ignored paths, and so
  whether that case also reads `capture-unchanged`.
- The Claude WRITE adapter's collapse points. The refusal review read Codex
  only.
- The operator step counts quoted during review (about 25 steps and two
  approvals falling to about 12 and one) are estimates from procedure text,
  not from a session log, and are not relied on here.
- Whether a real model can be reached outside a window at all.

## Records this draft leaves unchanged

These were named as stale and are left as written, for the reason given:

- `docs/ARCHITECTURE.md`, failure-test table, "across all twelve mutations".
  The facade has thirteen mutations (`api/control.py:482-673`). Whether the
  response-loss proof covers the thirteenth was not checked, so the claim about
  the proof is not edited.
- ADR 0021 (accepted) cites the egress design of ADR 0020 (proposed). ADR 0020's
  status line already records the relationship; accepted ADR text is not
  rewritten.
- ADR 0004, "M9 adds `canary`", and the lifecycle in
  `docs/designs/SELF_IMPROVEMENT.md`. No `canary` exists in `src`. Both
  describe design intent; M9's delivered scope is stated in
  `docs/ARCHITECTURE.md`.
