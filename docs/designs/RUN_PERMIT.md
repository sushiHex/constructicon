# Run permit — one law for admitting an unavailable executor

**Status:** proposal, 2026-11-12. Not accepted; nothing here is implemented or
authorized. Source references are to `main` at `c9f0c84`. It changes no
invariant and loosens no guard. One independent review pass is recorded at the
end; it refuted the first draft's central mechanism, and this version is the
result.

## The problem

Every live provider publishes itself as unavailable, and runs only when an
owner-placed file admits one exact run. That law was written twice.

| | Qualification | Maintenance |
| --- | --- | --- |
| Type | `QualificationAuthorization` (`core/qualification.py:41`) | `_AttemptAuthorization` and its two subclasses (`core/maintenance.py:105`, `:193`, `:206`) |
| Discriminator | `stage`, three literals | `purpose`, two literals |
| Run identity | `run_id` (`:126-129`) | `run_id` (`:158-160`) |
| Admission | `admits` (`:131-141`) | `admits` (`:162-168`) |
| Acquisition | `acquisition_faults` (`:143-174`) | `acquisition_faults` (`:170-190`) |
| WRITE grant shape | `:109-118` | `:145-154` |

Fourteen fields have the same name and meaning in both: `authorization_id`,
`actor_id`, `idempotency_key`, `scope`, `binding`, `source_graph_hash`,
`capability_id`, `revision`, `operator_binding_digest`, `journal`, `max_epoch`,
`not_after`, `grants` and `attempt_record`. The acquisition checks are the same
ten categories in the same order.

The copies are kept equal only by care, and they have drifted:

- **Epoch.** Qualification admits any `epoch <= max_epoch`
  (`qualification.py:171`). The review reproduced it accepting `0`, `-1`,
  `True` and `0.5`. Maintenance admits exactly the integer one
  (`maintenance.py:187`).
- **Grants.** Qualification treats absent pinned grants as a match
  (`qualification.py:158`). Maintenance always compares
  (`maintenance.py:186`).
- **Reading.** The maintenance reader refuses a repeated JSON key
  (`substrate/executors/maintenance.py:26`, `core/identity.py:45-66`). The
  qualification reader hands the bytes to Pydantic
  (`substrate/executors/qualification.py:35`), which keeps the last occurrence;
  the review reproduced this on the installed version.
- **Use.** The M9 selector runs under `stage="qualification-read"`
  (`api/m9_trial.py:54`, `:184`). It is not a qualification. The permit was
  already general; only its name was not.

A third live use today means a third copy of the law.

## What cannot move: the wire

The first draft proposed a base class holding the fourteen fields. That is
wrong, and the reason shapes the design.

**Field order is observable.** Three commands print a permit for the owner
with `model_dump_json()`, which follows declaration order
(`api/qualification.py:612`, `api/claude_qualification.py:253`,
`api/claude_write_qualification.py:495`). Tests pin those exact bytes
(`tests/core/test_qualification_write.py:177-210`) and the maintenance field
order and JSON Schema hash
(`tests/core/test_maintenance_channel_authorization.py:50-88`). A Pydantic
subclass keeps a redeclared field at its *base* position, so a shared base
would move `stage` and `purpose` and change printed bytes, schema and
missing-field error order.

So each model's field list stays exactly where it is. That list is not
duplication to remove. It is the wire schema of one era (ADR 0016), and two
eras legitimately have two.

## The design

**Share the law. Leave the wire alone.**

One L0 module, `core/permit.py`, holds what the two types *do*. It declares no
fields and no Pydantic model.

```python
# core/permit.py
class PermitFault(StrEnum):       # the ten checks, named once
    RUN, INVOCATION, BINDING, SOURCE_GRAPH, CAPABILITY, REVISION,
    OPERATOR_BINDING, GRANTS, EPOCH, EXPIRED

def run_id(permit) -> RunId: ...
def admits(permit, *, source_graph_hash, capability_id, revision) -> bool: ...
def faults(permit, *, run_id, path, binding, source_graph_hash, capability_id,
           revision, operator_binding_digest, grants, epoch, now
           ) -> tuple[PermitFault, ...]: ...
def fixed_write_grants(grants) -> bool: ...

Permit = QualificationAuthorization | MaintenanceAuthorization   # closed
```

- **The two types keep their names, fields, validators, serializer and
  refusal sentences.** Their `run_id`, `admits` and `acquisition_faults`
  become one-line calls into the law. `acquisition_faults` renders
  `PermitFault` into today's sentences, including each type's prefix and each
  type's epoch sentence, so every asserted string is unchanged.
- **`fixed_write_grants` is a plain predicate.** Each type's validator keeps
  calling it at the same point and raising its own message. Nothing is added
  as a base validator, so validator order does not change.
- **`Permit` is a closed union, not a base.** There is no instantiable general
  permit. Nothing validates a permit except as one of the five closed leaves.
- **The law functions accept only the closed union**, checked at entry.

This is the smallest change that removes the duplicated guard. It is also the
one the existing code already points at: `_AttemptAuthorization` shares one
law between the two maintenance tasks today (`maintenance.py:105-111`).

`PermitFault` is the first family for [REFUSAL_CODE.md](REFUSAL_CODE.md).

### Purpose and payload

A permit's **purpose** is one closed literal: `qualification-no-dispatch`,
`qualification-read`, `qualification-write`, `plan-manifest-maintenance`,
`channel-stored-reply`. Its **payload** is whatever only that purpose needs:
WRITE assembly pins for one, a task request and its application pins for
another. Purpose selects the leaf type; the leaf type fixes the payload's
shape. The literals are disjoint and every leaf forbids extra keys, so a permit
of one purpose never validates as another.

The wire keeps both discriminator keys, `stage` and `purpose`. No retained
byte is rewritten. The design adds a read-only `purpose` view to the
qualification type so code can ask one question of either.

### Three tightenings, each optional and each named

Sharing one law forces a choice wherever the copies differ. Each choice below
refuses more, never less. Each is separable, and each needs its own test.

1. **Epoch.** One rule: an integer from one to `max_epoch`. Qualification stops
   accepting zero, negatives, booleans and fractions. The journal's claim path
   mints positive integers (`substrate/journal/_sqlite_base.py:270-282`), so
   nothing known is refused.
2. **Reading.** The qualification reader uses the duplicate-refusing parser. A
   permit file that repeats a key is refused. Whether any retained file does
   is not known.
3. **Grants.** No change: absent pinned grants keep matching for the
   no-dispatch stage, which pins none by its own validator
   (`qualification.py:102-103`). The law states this rule once.

Not unified, deliberately:

- **Field strictness.** Qualification's fields are bare strings; maintenance's
  are strict and bounded. Bounding the former could refuse a retained permit.
- **The capability pins.** `QualificationCapabilityPin`
  (`core/qualification_write.py:30-36`) and `MaintenanceCapabilityPin`
  (`core/maintenance.py:96-102`) differ in the same way; the review reproduced
  the former accepting a 257-character id. They are wire shapes and stay two.
- **The readers.** They already share the root-custody primitive
  (`qualification.py:40-71`). The maintenance reader also accepts a file with
  no `purpose` as a plan-manifest permit (`maintenance.py:25-29`,
  `core/maintenance.py:202`). That behaviour is kept as it is.

## Is the root-file permit the same idea as an `ApprovalRecord`?

No. They are two ideas with one shape.

| | Run permit | `ApprovalRecord` (`core/effect.py:336-347`) |
| --- | --- | --- |
| Question | May this run reach an executor that is otherwise unavailable? | Does a human approve this exact effect? |
| Trust root | Host custody: a root-owned `0640` file under root-owned directories | An authenticated actor in the control plane |
| Lives | Outside the journal, and names the journal's path | Inside the journal, sealed |
| Acts | Before the run exists: admission and acquisition | Inside an existing run: an effect's proof |
| Constrains | The runtime itself | A subject the runtime evaluates |

The shape is shared: an exact subject, a single use, an owner's decision. The
trust roots are not. The runtime authenticates approval actors and writes the
journal, so a journal fact cannot be what limits the runtime's reach into a
subscription store.

Durability differs by purpose. A no-dispatch permit tolerates a journal reset
by design. A dispatching permit is bounded across resets by its external
attempt record, not by the permit file (`qualification.py:10-14`, `:44-47`).

They could converge only if live runs moved into the standing journal with the
journal as the sole attempt budget, and even then the credential would remain
host custody. That is a separate decision. This design keeps them apart.

## Concepts retired

| Retired | Replaced by |
| --- | --- |
| The second copy of run identity, admission and the ten acquisition checks | `core/permit.py` |
| The second copy of the fixed WRITE grant shape | one predicate |
| Qualification's looser epoch rule | the one rule |
| Qualification's duplicate-tolerant read | the one parser |
| "Qualification" as the word for any one-run live permit | "permit"; qualification is three of its five purposes |

Introduced: `PermitFault`, which names ten checks that already exist, and the
`Permit` union, which names two types that already exist.

Not retired, though the first draft claimed them: the two wire models, the two
capability pins, the two reader functions, and the two provider slots. The
last is addressed next.

## The provider slot: deferred, with its obligations

The Codex provider holds `qualification` and `maintenance` separately and
checks they are exclusive (`substrate/executors/codex.py:2321-2325`). One slot
typed by the closed union would make that guard unrepresentable. It is not
proposed now, because the slots carry behaviour that a merge must reproduce
exactly:

- maintenance-only posture, grant-policy, configured-model and effort checks
  (`codex.py:2461-2471`);
- `purpose` added to the durable attempt identity for maintenance only, and
  dispatch disabled for the no-dispatch stage (`codex.py:2524-2538`);
- the Claude provider's supported-stage, workspace and fixture restrictions and
  its custody snapshot (`claude_provider.py:238-249`, `:283-294`). Claude
  supports neither maintenance purpose, and a shared table must not widen that;
- task-specific assembly checks that read the slot by name
  (`api/plan_manifest_application.py:540-560`).

Merging the slots would turn each of these into a type test on one field. That
removes one guard and rewrites four, for little gain. It should wait until a
third purpose makes the two-slot form actually awkward.

## Migration

"Moves" lists the source-derived identities a step changes. Revision source
lists are explicit and not transitive: importing a module does not hash it.

| Step | Change | Moves |
| --- | --- | --- |
| 1 | **Fill the golden gaps, tests only.** Existing tests pin qualification no-dispatch and read bytes and the plan-manifest maintenance bytes, digest, schema and run id. Add: the WRITE stage and the channel-reply purpose; the qualification JSON Schema hash; every refusal sentence for each of the ten checks on both types; the three printed-permit commands' output. | Nothing |
| 2 | Add `core/permit.py`. Both types call it. **Add the new module to every source list that hashed the law before:** the maintenance application revision (`api/_maintenance_identity.py:14-18`) and the Claude adapter revision (`claude_provider.py:881-885`). Update the mutation needles that quote the moved predicates (`scripts/check_m8_mutations.py:305-369`, `:985-997`; `scripts/check_m8_n5_stage1_mutations.py:38-48`; `scripts/check_m8_n5_write_mutations.py:27-63`). | The maintenance application revision; the Claude adapter revision |
| 3 | The epoch rule, with its test. | As step 2 |
| 4 | The duplicate-refusing read for qualification, with its test. | The maintenance application revision (`substrate/executors/qualification.py` is in its list) |
| 5 | Wording: `ARCHITECTURE.md` gains a short "Live execution" section naming the permit. Frozen procedures that quote the old names are not edited (`docs/plans/MANIFEST.sha256`). | Nothing |

Three facts about cost:

- **Only step 1 is free.** Steps 2 to 4 edit files that revisions hash whole.
  Slicing differently does not help: the duplicated law is itself inside the
  pins. They should land together, inside the planned requalification.
- **Without the list additions in step 2 the change would weaken a pin.** The
  law would leave the hashed files and later edits to it would move nothing.
- **Any source change moves two wider identities**, and this one is no
  exception: the installed controller tree, and the M9 selector's source
  identity, which hashes every package file (`api/_m9/proposer.py:52-81`), so
  existing trial directories stop matching their marker
  (`api/_m9/trial.py:46-62`).

## The strongest case against

*Separate types are a guard. The code says so: "This is separate from N5
qualification" (`maintenance.py:199`) and "qualification requires its separate
authorization" (`codex.py:2327`). And after the review, what is left to gain?
The wire stays duplicated, the pins stay, the slots stay. The proposal now
moves two revisions to delete about sixty lines.*

- **Separation is untouched.** The types, their literals, their payloads and
  every check that distinguishes them stay exactly as they are. The law is
  shared the way `canonical_json` is shared: by call, not by kinship.
- **What is left is the part that was dangerous.** Field lists that differ are
  visible in review. A predicate that silently differs is not, and this one
  already accepts a negative epoch in one copy. A guard maintained twice by
  hand is the thing the project's own rule warns against.
- **The cost objection stands, and the schedule concedes it.** Only tests land
  before the planned requalification. If that requalification is not taken,
  steps 2 to 4 should not be taken either, and the goldens remain as the
  record of where the copies differ.

## First PR

Step 1 only. Tests, no source, nothing moved. It is worth having even if the
rest is declined: it records exactly where the two copies agree and differ,
which today is known only by reading both.

## Open questions for the owner

1. **Adoption.** Take steps 2 to 4 inside the planned requalification, or keep
   only the goldens?
2. **The epoch tightening.** Accept it, or keep qualification's rule and
   parameterize the law by type?
3. **The read tightening.** Accept it without evidence about retained permit
   files, or first inspect them on the host?
4. **The name.** Use "permit" in code and prose while the wire key
   `authorization_id` and both class names stay?
5. **The M9 selector.** Leave its borrowed stage as named history, or give it
   its own purpose later? A sixth purpose is a new wire literal and a new M9
   trial identity.

## Review record

One pass by an independent model, asked to attack the first draft with the
repository mounted read-only. Each premise below was then checked at source.

| Finding | Checked | Result |
| --- | --- | --- |
| Field order is printed and pinned, so a fielded base changes bytes | `api/qualification.py:612`; `test_qualification_write.py:177-210` | Confirmed. The base class is withdrawn; the law is shared by call |
| The two capability pins do not accept the same inputs | `qualification_write.py:30-36`, `maintenance.py:96-102` | Confirmed. They stay two |
| Extracting the law drops it from explicit source lists | `_maintenance_identity.py:11-19`, `claude_provider.py:881-885` | Confirmed. Step 2 adds the module to both lists |
| The M9 source identity hashes every package file | `_m9/proposer.py:52-81` | Confirmed, for any source change. Stated in the cost notes |
| One slot must reproduce per-slot behaviour | `codex.py:2461-2471`, `:2524-2538` | Confirmed. The slot merge is deferred with its obligations listed |
| A general base could be instantiated and accepted | design text | Accepted. There is no base; `Permit` is a closed union |
| A discriminator-dispatching reader would refuse a file with no `purpose` | `executors/maintenance.py:25-29` | Confirmed. The readers are left as they are |
| Fourteen shared fields, not thirteen; the ten checks share categories, not predicates | `qualification.py:158-172`, `maintenance.py:175-188` | Confirmed. Corrected above |
| Mutation needles quote the moved predicates | `scripts/check_m8_mutations.py:305-369` | Not opened; taken from the review and listed in step 2 |

## Not verified

- Pydantic's duplicate-key behaviour on the locked version. The review ran the
  installed one; the lock names a later release.
- Whether any retained permit file on a host repeats a key or carries a field
  that stricter bounds would refuse.
- The mutation-needle line ranges in step 2, which come from the review.
- Operator packages outside the repository, which may parse or print permits.
- That the journal mints only positive integer epochs on every path. One claim
  path was cited by the review and not traced further.
