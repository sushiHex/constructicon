# Instruction binding: the instruction is pinned as the target is

Status: accepted by the owner on 2026-11-12 (see "The decision") and
implemented. Tracks
[#407](https://github.com/sushiHex/constructicon/issues/407). Not an ADR, and
no authorization for a live window.

## Problem

A maintenance instruction is installed code. Its wording is bound by coarse
hashes, and its own identity appears nowhere the owner can see.

| Where the wording is bound today | Evidence |
| --- | --- |
| The whole application file, hashed as the node bodies' adapter revision, then the component version, then the source graph hash | `api/plan_manifest_application.py:279,289,297,320`; `runtime/registry.py:357-372` |
| The same file again, with seven others, as the application revision | `api/_maintenance_identity.py:11-19` |
| The installed controller tree | every `src/constructicon` byte |

No request, authorization or attestation field names the instruction. The
owner's preview is the authorization dump
(`api/maintenance_entry.py:367-372`). Generation 18 spent an owner-approved
window on wording; correcting wording costs a controller install, an install
approval and new authorizations.

## Design

One sentence: **the instruction becomes a file of the reviewed base commit,
pinned in the request by SHA-256 exactly as the target file already is.**

The target is already handled this way. The request carries `target_sha256`;
assembly reads the bytes from the pinned base in the private authority into
`MaintenanceResources.target_source`; `require_maintenance_resources` refuses
drift. The instruction follows the same path.

1. **Where the bytes live.** `maintenance/<purpose>.txt`:
   `maintenance/plan-manifest-maintenance.txt` and
   `maintenance/channel-stored-reply.txt`. The path is derived from the
   purpose literal, so the task table gains nothing. The files are outside
   `src/`, so they are in no source-derived revision and not in the installed
   controller tree. `.gitattributes` marks them `text eol=lf`. The bytes are
   used exactly as committed, with no newline or Unicode normalization.
2. **How they travel.** Inside the reviewed bundle, which is already
   transferred, digest-checked before Git parses it and fetched into the
   private authority (`api/_maintenance_source.py:123-155`). There is no new
   artifact, argument or parser.
3. **What binds them.** The two request models gain `instruction_sha256`.
   Assembly computes it from `git show <base>:maintenance/<purpose>.txt`, next
   to `target_sha256` (`api/maintenance_entry.py:149-159`). The request is
   already inside the authorization, so the preview carries the digest, and
   the existing whole-request equality binds it (`maintenance_entry.py:192`,
   `plan_manifest_application.py:578`).
4. **How the writer receives them.** As a second declared run input,
   `instruction`, beside `request`, on the graph and on the writer. Assembly
   reads the text into `MaintenanceResources.instruction`; the entry submits
   both. The writer refuses unless the text's SHA-256 equals
   `request.instruction_sha256`, then builds its `TaskSpec` from it. The two
   recorded-input comparisons (`maintenance_entry.py:228-232`,
   `plan_manifest_application.py:651-654`) are extended to both inputs, so
   recovery from a journal is held to the assembled text before startup. The
   journal then retains the exact application instruction supplied to the
   run. That is input evidence, not dispatch evidence: the vendor adds its
   own messages around it.

   Rejected: the writer reading the file through its workspace path. A
   contained workspace is populated and guarded by the launcher
   (`substrate/git/contained.py:99-121,246-270`); a node body reading that
   directory on the host would be new ambient reach.
5. **What is refused.**

   | Refusal | Where |
   | --- | --- |
   | `maintenance base lacks its task instruction` (absent, or not a `100644` blob) | preparation, assembly, resources check |
   | `maintenance instruction is not bounded UTF-8 text` (empty, over 8192 bytes, or undecodable) | the same three |
   | `maintenance instruction omits the installed helper` (channel task only) | the same three |
   | `maintenance instruction differs from its pinned digest` | resources check, and the writer before dispatch |
   | `maintenance request carries no instruction digest` (an era-1 request) | assembly comparison, and the writer |

   What an operator sees: the writer's two refusals are added to the
   diagnostic's closed cause map (`maintenance_diagnostic.py:67-79`) as
   `writer-instruction`. Preparation and preflight keep their existing coarse
   stage (`maintenance_entry.py:449-457`); carrying a specific cause through
   that boundary is the closed refusal-code work, not this change. A refusal
   at preparation leaves a root that must be discarded, exactly as an unfit
   channel base does today (`_maintenance_source.py:163-169`); no session,
   authorization or dispatch exists yet.
6. **Oracle parity.** The channel instruction interpolated the oracle's
   `HELPER_SOURCE`. As data it holds a copy, so installed code requires the
   instruction to contain the installed oracle's helper, indented as a
   method, byte for byte. A repository test asserts the same of the committed
   file, and that both files state the mediation limits equal to the code's
   constants (the existing test, now reading the files; the real-binary
   placement lane keeps asserting the committed text is the last user turn).

### Eras

Retained version-1 bytes must keep decoding. A never-regenerated golden pins
them (`tests/core/test_maintenance_channel_authorization.py:26-28`), and the
diagnostic and report decode recorded requests through these models
(`maintenance_diagnostic.py:278`, `maintenance_report.py:361`).

So each request model stays one class with two eras: `schema_version` 1 has
no `instruction_sha256` and serializes exactly as before; `schema_version` 2
requires it. Era 1 is history only. Assembly builds era 2, and the resources
check, the pre-startup attempt check and the writer each refuse a request
without a digest, so the maintenance entry admits no era-1 authorization. No
digest is invented for old bytes.

That refusal lives in the maintenance entry and its writer, not in generic
graph admission, which validates port names and contracts and not request
values. A second entry point to these graphs would have to keep it.

### Removed

`TOOL_PREFIX`, `WRITE_INSTRUCTION`, `CHANNEL_INSTRUCTION` and
`MaintenanceTask.instruction`.

### Deliberately not done

- **Replacing the node bodies' whole-file adapter revision with the
  application revision.** Review refuted it: it would make an entry-only edit
  change component versions and the source graph, which is new invalidation,
  including for an available executor where the application comparison is
  conditional (`plan_manifest_application.py:572`). The existing hash stays.
  It stops depending on wording because the wording leaves the file.
- **Moving CLI diagnostics out of the application revision.**
  `maintenance_entry.py` holds `require_maintenance_attempt`, which decides
  admission. That split needs its own review.
- **Changing `SourcePin`.** It fixes the bundle digest and base commit;
  assembly and the resources check reread the exact base blob and hold it to
  the approved digest. This is sound inside the existing private-authority
  custody boundary and no further.
- **Carrying the text in the request.** The authorization reader is bounded
  at 8192 bytes (`substrate/executors/qualification.py:24`). A digest is
  fixed width: it adds 88 bytes to a representative 1,723-byte authorization.
- **Generalizing to qualification or M9.** Their instructions are separate
  inline constants with their own identities.

## The decision

This design changes who selects the instruction. That is a change to a
stated guarantee, so it was the owner's to make.

**Owner decision, 2026-11-12: accepted, before generation 19.** The successor
guarantee below is accepted as written. The two source docstrings now state
it. The frozen records named below describe the earlier guarantee and are
left unchanged, as superseded records are.

Today the guarantee is: "Neither task's instruction or exam is
caller-selected" (`plan_manifest_application.py:8-10`,
`core/maintenance.py:32,63`). The frozen task and delivery records say the
same: "a fixed constant", "no caller-selected instruction"
(`docs/plans/handoffs/maintenance-channel-reply-task.md:22-24,71`,
`maintenance-channel-reply-delivery.md:48`). Choosing a base commit cannot
choose the instruction.

Under this design, choosing a base commit proposes the instruction, and the
owner's approval of the exact request disposes. The successor guarantee:

> The exam is never caller-selected: it is installed code, pinned by the
> check set. The instruction is the reviewed base commit's file at a path
> fixed by the task's purpose. Its SHA-256 is in the request the owner
> approves, and the writer refuses any other bytes. Nothing at run time
> selects it.

Digest binding proves which instruction was selected. It does not preserve
installed code as the selector. No mechanism does both: either installed
code names the wording, and every wording edit is an install, or the owner
approves the wording by digest. The acceptance is recorded here and in the
handoff; an ADR would make it durable if the owner wants one.

What an instruction can cause is unchanged, and is the reason the trade is
small:

- Acceptance is decided by the installed oracle over the whole module's
  syntax tree (`substrate/gates/channel_reply.py:139-144`) and by the
  attestation, ancestry and exact-delta checks
  (`plan_manifest_application.py:660-699`). The instruction configures none
  of them. A hostile or mistaken instruction can waste the attempt; it cannot
  produce an accepted candidate.
- The grant shape stays validator-fixed (`core/maintenance.py:141-153`). The
  contained worker stays networkless. The executor's own provider egress is
  allowed, as now.
- The instruction file is one more baseline path, so a candidate that edits
  it fails the existing inventory comparison in both check programs
  (`plan_manifest_application.py:379-397,461-483`).

## What stays true

- **I3.** The writer gains no capability; the text arrives as a declared
  input.
- **I12.** The check set and its embedded oracle are untouched. The learner
  still cannot define its exam.
- **ADR 0002, 0003, 0006.** The manifest names exact component versions; the
  attestation binds manifest, check set and subject; request and instruction
  are recorded run inputs.
- **ADR 0016.** Old bytes decode as what they were; absent provenance stays
  absent.
- **ADR 0020 (proposed) and 0021.** The `TaskSpec` is still built inside the
  trusted writer with one instruction and no context.

## Remaining objections

1. **"A data copy of the helper can drift from the oracle."** Refused by
   name by installed code at preparation, and tested in the repository.
2. **"A run input is caller-supplied."** The entry supplies it; the
   pre-startup comparisons hold recorded inputs to the assembled ones; the
   writer's digest check makes the approved request the authority.
3. **"Windows checkouts rewrite line endings."** The digest is of the Git
   blob, read with `git show` in the private authority. The attribute keeps
   working copies LF so tests read the same bytes.
4. **"One more install is needed."** Yes: the controller that reads the
   instruction from the base. Generation 19 needs an install regardless. It
   is the last one a wording edit causes.
5. **"Run inputs are not a secret-filtering surface."** Correct. The
   instruction is public repository text; it is bounded before submission and
   retained as private evidence like the rest of the journal.

## What changes identity

| Pin | Changes once, with this design | Changes on a later wording edit |
| --- | --- | --- |
| Application revision | yes | no |
| Component versions, source graph hash | yes (request port schema, new `instruction` port, edited bodies) | no |
| Installed controller tree | yes | no |
| Base commit, bundle digest, check set hash (baseline inventory) | per window, as now | yes, as for any new base |
| `request.instruction_sha256` | new | yes: the one owner-visible statement |
| Protocol, adapter, launcher, workspace revisions; gate recipe; `SourcePin` wire | no | no |

A wording edit is not prose-only for CI: a new path under `maintenance/`
selects the full lanes (`scripts/ci/m8_ci_scope.py:138`).

## Readers and pinned text to update

- **Request models** (`extra="forbid"`): constructors and goldens in
  `tests/core/test_maintenance_authorization.py`,
  `tests/core/test_maintenance_channel_authorization.py`, the entry tests,
  the rehearsal and preflight readers (`tests/e2e/maintenance_rehearsal.py`,
  `tests/preparation_preflight.py`, `tests/substrate/test_codex_host.py`,
  `tests/test_channel_reply_operator_package.py`,
  `tests/test_m8_maintenance_session.py`) and the diagnostic fixtures. Era-1
  goldens stay byte-identical; era-2 cases are added.
- **Root authorization reader** (`substrate/executors/maintenance.py:28-29`):
  follows the models.
- **Mutation inventories**: literal guard lines for request equality,
  recovery inputs and the preview bound (`scripts/check_m8_mutations.py:271,
  287,942,970,988`) must stay live; the new digest refusals need real
  mismatch cases, not renamed ones.
- **The diagnostic's cause set** gains `writer-instruction`. Frozen operator
  packages enumerate the causes they accept (g11:
  `docs/plans/handoffs/M8-maintenance-g11-continuation.md:743`); a later
  package must accept the new one.
- **Constant consumers**: `tests/api/test_plan_manifest_application.py`,
  `tests/api/test_channel_reply_hostile_replies.py`,
  `tests/substrate/test_channel_reply_oracle.py`,
  `tests/substrate/test_contained_gates.py`,
  `tests/substrate/test_provider_placement.py`.
- **The operator package's review record**
  (`docs/plans/handoffs/maintenance-channel-reply-session.md:421,863`,
  frozen) selects its own keys and omits the new digest. Approval of the
  whole preview hash still binds the field, but the abbreviated record would
  not show it. The generation-19 package must add `instruction_sha256` to
  that record and to the posted scope. That is package work.

## Effect on the operator (estimate from the procedure documents)

A wording edit today: a commit, a controller install with its own approval,
removal and reinstall steps, a post-install qualification, a new source
export, then preparation, preflight, approval and run. After this design: a
commit, a new bundle, preparation, preflight, one approval and run.

## Review record

One `gpt-6-astra` pass on the first draft, premises checked at source.

| Finding | Class | Disposition |
| --- | --- | --- |
| The design changes who may select the instruction; frozen records promise more | blocking, design choice | Put to the owner, who accepted it on 2026-11-12 |
| Version-1 requests would stop decoding; a never-regenerated golden and two readers depend on them | blocking, introduced | Fixed: one model, two eras |
| Named refusals vanish at the operational boundary | must-fix, pre-existing masking | Writer refusals mapped in the diagnostic; the coarse preflight stage is recorded as pre-existing |
| Application revision as adapter revision adds new invalidation | must-fix, introduced | Dropped; the existing hash stays |
| Recovery restores a checkpoint without rerunning the writer | note | The pre-startup input comparison covers both inputs |
| "Exactly what the model was asked" overclaims | note | Reworded to input evidence |
| Preparation is not transactional | note | Stated |
| Worker networkless, executor egress allowed | note | Stated separately |

One `gpt-6.1-sol` pass on the implementation.

| Finding | Class | Disposition |
| --- | --- | --- |
| The digest guard encoded with replacement, so a lone surrogate could match a request pinning `sha256(b"?")` | introduced | Fixed: strict encoding, and empty text is never an instruction; both cases tested |
| Generic admission accepts an era-1 request; the refusal is the entry's and the writer's | design choice | Stated under "Eras" |
| Helper containment proves inclusion, not meaning | design choice | Unchanged; the oracle decides acceptance |
| The q12 and q13 frozen cause lists also reject the new cause | design choice | No test compares them with the installed set; recorded for the next package |

It confirmed the era-1 wire in every dump path, both inputs reaching the
writer by nominal binding, the instruction files as the removed constants plus
one line feed, and every mutation needle matching once. It did not run the
Linux lanes.
