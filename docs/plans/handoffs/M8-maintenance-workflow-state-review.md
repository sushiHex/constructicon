# M8 maintenance workflow: state and evidence review

Revised contract for [#183](https://github.com/sushiHex/constructicon/issues/183)
and [PR #184](https://github.com/sushiHex/constructicon/pull/184). The owner
selected autonomous data-only vectors over arbitrary candidate Python and human
coverage approval. This replaces the earlier conditional human-review design.
Target source: `ecdb4c35b94dbddf1739a6fcefdce81ec561cb2f`.
This slice is credential-free construction; deployment and a live turn are separate.
This is the target-source pin, not the future candidate-tree base. The trusted
harness and fixed repository consumer must land first. Pin that implementation
head as the candidate base, preserving the target bytes from the source pin,
before proposing the new JSON file. Otherwise the JSON would be unused data.

## Candidate and closed input contract

The candidate adds exactly one absent regular file, mode `100644`:
`tests/vectors/plan_manifest.json`. Every other tracked path, mode and blob must
equal the pinned base. No rename, deletion, symlink, gitlink, existing-file
replacement, executable mode or unchanged candidate is accepted. The model
supplies data only; no candidate module, expression, command or expected result
is interpreted as code. Publication retains a candidate Git ref, without
installation, push, PR creation, promotion or merge.

The UTF-8 JSON document is at most 32,768 bytes and has exactly
`{"version":1,"cases":[...]}`. Version is integer 1, never a boolean. Cases
number 1..64; duplicate keys, unknown fields, non-finite numbers and wrong types
refuse. Each case has exactly one of these shapes:

- `{"kind":"plan_path","path":"..."}`: 0..256 ASCII characters.
- `{"kind":"entries","blob_hex":"..."}`: lowercase hexadecimal, even length,
  decoding to 0..1,024 bytes. Bytes must be ASCII or fail strict UTF-8 decoding;
  well-formed non-ASCII UTF-8 is outside this bounded profile.

Case identifiers are trusted array indices. There are no authored expectations.
The entire document is checked before any case runs. Successful `entries`
results contain at most 16 entries; rendered source is at most 262,144 bytes
and each process output is at most 65,536 bytes. The profile covers logical
parser inputs, including ASCII controls;
case paths are never materialized as filesystem paths.
The suite must include permitted and refused paths, nonempty successful
entries, an entries `ValueError` case and an invalid UTF-8 case. An empty
entries result alone is not positive evidence of a successful record parse.

## Reviewed reference rules and finite exam

The trusted reference is authored from these explicit rules and verified
differentially against the pinned implementation. Its authors read the target;
this is independently specified expected behavior, not a claim of source blindness.
`plan_path` accepts canonical relative POSIX spelling with no empty or dot
segments, no whole `..` segment, backslash, colon, CR or LF, and a final
`.md` suffix with its last dot at an index greater than zero. A final segment
equal to `.md` has no suffix and refuses; this is the reviewed CPython 3.11/3.12
profile, not an inference from a different runtime's `PurePosixPath` behavior.
Absolute, drive/UNC and normalized spellings refuse. Spaces, tabs and other
ASCII characters are not generally banned; a leading-space ` a.md` and
`..md` can pass. Preserve the target's pure lexical behavior.

For `entries`, strict UTF-8 decode failure is `UnicodeDecodeError`.
ASCII line boundaries are CRLF, CR, LF, VT, FF, FS, GS and RS. A line beginning
with `<<<<<<<`, `|||||||`, `=======` or `>>>>>>>` refuses. Blank lines
use ASCII whitespace including US. Each other line splits at its first exact
double-space delimiter: digest is exactly 64 lowercase hexadecimal characters,
path satisfies the reference path rule, and duplicate paths refuse even with
equal digests. Other malformed input raises `ValueError`. CRLF is a line
ending; triple-space delimiter spelling may yield an accepted leading-space
path. No blanket whitespace normalization or extra refusal is invented.

A reviewed fixed matrix positively exercises permitted paths and valid
multiple/blank entries, plus every refusal class, controls, split-line forms,
duplicates and invalid UTF-8. Differential checks cover this matrix and bounded
generated inputs. Disagreement fails construction; production rules do not
change to satisfy a mistaken expectation.

Candidate acceptance requires baseline agreement for every case and an
assertion-failing case against each named finite mutant in the trusted harness.
Mutation targets/replacements occur exactly once and are fixed before the
model turn: `path_absolute`, `path_noncanonical`, `path_parent`,
`path_unsafe_characters`, `path_any_suffix`, `digest_relaxed`,
`entries_duplicate_overwrite` and `entries_conflict_skip`. The unsafe-character
mutant removes the combined backslash/colon/CR/LF guard. Conflict skip changes
refusal to skipping; merely removing that guard still errors and is not a kill.
A surviving mutant, syntax/import error, non-assertion exception, timeout,
overflow, zero executed tests or incomplete teardown refuses. The finite
inventory measures these named changes; it proves no universal defect coverage.

The trusted renderer emits stdlib `unittest` bytes with one fixed assertion
per case and expectations from the reference. It embeds only the SHA-256-checked
pinned target source, applying an exact fixed replacement for each mutant.
Literal encoding is controlled by trusted code. No candidate Python executes, so candidate reports cannot
replace execution facts. The emitted module is private scratch, not a second
candidate path. Retain its digest and deterministic recipe (vector bytes plus
pinned harness identity); regenerate the bytes when needed. Do not label an
unstored digest an `ArtifactRef`. A fixed trusted repository consumer makes
the retained JSON executable regression data during normal verification.

## Existing Graph and assembly

One strict `Graph` is admitted to one sealed manifest and scheduled by the
existing walker: `writer -> checker -> accepted evidence`. Explicit maps bind
candidate `GitRef` and `MergeEvaluation`; passing checks complete autonomously.
There is no human-advisor, parked review, repair loop or merge capability.

Reuse native WRITE `CodexOperatorProvider`/`CodexOperatorHandle` and the
`contained_python` catalog. Pass only `TaskSpec.instruction` and the admitted
contained workspace: current Codex refuses context/response-schema fields.
Reuse `ContainedWriteWorkspaceProvider` (`workspace.contained`), await
`commit_all`, and import only its verified immutable capture pack.
The checker verifies the entire candidate tree against base before accepting
the one JSON delta. WRITE containment alone is not a path restriction.

Reuse `ContainedGateRunner.create` (`gates.contained`) and awaited
`BoundContainedGate.verify`. Trusted fixed programs run baseline and finite
mutants over the exact prepared READ snapshot, using `/usr/bin/python3 -I`
and stdlib; trusted code sets the target import location explicitly. Private
scratch contains rendered modules/mutants and is removed before attestation.
Candidate, base, target, runtime, harness, renderer, mutation bytes, instruction,
bounds and definition source bind the relevant application/check identities.
Installed revisions derive from actual factories, never historical g8 pins.

Application writer/checker definitions have restart-importable `PythonRef`s,
typed requirements and complete schemas. The injection root imports the
pinned base into private `GitAuthority`, assembles one journal/authority/
launcher, and registers/promotes local definitions through existing durable
commands with trusted static admin and caller keys. Introspection was inspected
in the preceding design; assembly must describe its actual registered capability
and component inventory. Preserve N5's fixed empty-seed/`n5-write.txt`
qualification entry points and every historical source byte.

## State at await and cleanup

| Boundary | Possible resumed state and required action |
| --- | --- |
| Runtime probes | Completed/cancelled probe; join teardown and refuse drift before revision publication. |
| Acquire/materialize | Recorded row, inert handle, or exposed processes/workspace; enroll cleanup before exposure and recheck control. |
| Base read/model return | Target/control may change; require exact base, `ExecutorSuccess`, quiescent descendants and current control before capture. |
| Capture | Candidate publication may exist before reply; require exact changed ref and capture's atomic closure fence. Presence alone is not writer completion. |
| Writer checkpoint/close | Checkpoint may be durable; recover it without another turn, join release and preserve cleanup failure. |
| Immutable reads/rendering | Candidate/base may drift and scratch may exist; validate tree/schema fully, join metadata workers and clean scratch. |
| Gate | Prepared snapshot/check/attestation may exist; require current base, complete baseline/mutant evidence and joined teardown before fenced minting. |
| Checker checkpoint/close | Evaluation may be durable; recover exact result and join gate closure before success. |
| Cancellation/ownership loss | Loss may latch during teardown; relinquish local custody without closing successor resources. Shutdown abandons, never invents user cancellation. |

Writer success closes with `release`, retaining its candidate and removing
mutable payloads. Checker failure retains that released candidate as unaccepted.
Failed/cancelled writers discard; counterfactual acquisitions discard separately.
Death after checkpoints recovers through existing rows/fences. No new pruning
effect, cleanup service or outcome inferred from an empty fault list is added.

## Credential-free acceptance and limits

The fake path drives this exact graph with genuine controllable doubles.
Substitute only platform launch primitives so lifecycle checks actually run on
Windows; separate Linux checks establish physical capture/gates/runtime.
Prove an accepted one-file candidate with positive case counts and all named
assertion kills; malformed/spoofing data, wrong tree/mode, no change,
executor/gate failure, surviving/erroring mutants, bounded overflows and drift
must refuse. Exercise cancellation, ownership loss and death at materialization,
model return, capture publication, gate completion and checkpoint/close seams.
Assert checkpoints, exact refs/evaluation, capability accounting, target
unchanged and measured teardown facts. Written or skipped tests are unverified.

Existing g8 WRITE passed at its observed `59de73b` boundary; that establishes
neither present availability nor authorization for this graph. Fresh exact-profile
deployment, qualification, authenticated startup and a bounded live-task
authorization remain separate. No vendor process, VM operation, credential
access, live attempt or merge is needed for this slice. Claude/Pi and M8 closure
remain separate; recorded vendor identity/telemetry limits stay unchanged.
