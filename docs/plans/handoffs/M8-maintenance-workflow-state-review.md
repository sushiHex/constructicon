# M8 maintenance workflow: state and evidence review

Draft for [#183](https://github.com/sushiHex/constructicon/issues/183), not accepted authority.
Source: `ecdb4c35b94dbddf1739a6fcefdce81ec561cb2f`, `plan/m8-practical-next`.
Design precedes accepted implementation; no blocker or live/credential action.

## The bounded contribution

The candidate adds exactly one previously absent regular, non-executable file:
`tests/test_plan_manifest_paths.py`. It is a stdlib `unittest` suite importing
the real `scripts.regen_plan_manifest.plan_path` and `entries` functions. It
does not copy their implementation, change them, run the refresh command or
modify the index. All other tracked paths, modes and bytes remain equal to the
pinned base. A rename, deletion, executable bit, symlink, gitlink, unrelated
edit, existing-path replacement or candidate equal to the base refuses.
Publication means retaining a candidate Git ref for review. It does not mean
installing the candidate, pushing, opening a PR or advancing any target ref.

Existing `tests/test_regen_plan_manifest.py` proves refresh transactions,
conflicts, a short invalid-name list and additions with nested paths/spaces.
The gap is a direct stdlib matrix for both pure functions, not a known defect.

The independently fixed matrix includes permitted `a.md`,
`handoffs/nested/review.md` and `handoffs/new file.md`; refused traversal,
absolute POSIX paths, drive paths, UNC forms, backslashes, CR/LF, `./`, doubled
or trailing separators, wrong suffixes and empty names. `entries` covers an
empty/blank input, valid multiple entries including spaces, the same path
repeated with equal or different digests, malformed lengths/uppercase/non-hex
digests, missing delimiters, invalid paths, conflict markers and invalid UTF-8.
Assertions follow actual base semantics: `entries` uses `splitlines`, so a
normal CRLF line ending is not a CR-containing path. Do not demand its refusal
or silently change production semantics to accommodate a mistaken test.

## Reuse and the assembly boundary

The execution remains one strict `Graph`, admitted to one sealed manifest and
scheduled by the existing walker:

```text
writer -> checker -> review-request -> human-advisor
   |          |                            |
candidate  evaluation               authenticated advice
```

Explicit maps bind each result. Successful Graph outputs expose `GitRef`,
`MergeEvaluation` and `AdviceReplyPayload`; while PARKED root outputs are empty,
so candidate/evaluation are read from checkpoints and the durable request.
Advice is not merge authority. No repair loop, promotion or merge is included.

Reuse the existing task-shaped `Executor`/`ExecutorProvider`,
`CodexOperatorProvider` and `CodexOperatorHandle`, native WRITE profile and
`contained_python` callback catalog. The writer passes only `TaskSpec.instruction`
and its admitted contained workspace to `execute`. Current Codex refuses
`TaskSpec.context` and `response_schema`; READ cannot receive a workspace.
The model can operate only in the worker's bounded WRITE mount; it receives no
GitHub token, journal, authority locator or installation capability.

Reuse `ContainedWriteWorkspaceProvider` (`workspace.contained`), await
`commit_all`, and export the resulting `GitRef`. Capture imports only a verified
immutable pack. Reuse `ContainedGateRunner.create` (`gates.contained`) and await
`BoundContainedGate.verify`; it checks the prepared merge against current base,
exports an exact READ snapshot, bounds execution, tears down descendants and
removes transient files before journal minting. Check argv and inline trusted
program bytes are part of the existing gate runtime/check-set identity.

Reuse `MailboxChannel` (`channel.mailbox`) over the exact system journal,
`ChannelSendEffect` with that exact transport, and the explicitly registered
`constructicon.std/human-advisor` definition from `sdk.std.definitions()`.
Its `advisor` alias has one input `constructicon.std/AdviceRequest` and one
output `constructicon.std/AdviceResponse`; assembly fixes lane, interaction
`advice` and recipient on `ChannelEndpoint`. `channels_reply` obtains the actor
from the transport. The standard reply carries authenticated `actor_id` and
derived `message_id`; an advisor does not supply those as payload authority.

Application-only definitions remain: writer, checker and pure review-request
builder. They need restart-importable `PythonRef`s, complete requirements and
embedded request schemas. Assembly registers them and the advisor through the
existing local `ControlPlane` command law with a trusted static admin and caller
keys, then fixes capability IDs, root grants, exact versions and bounds.
The parent executed a scratch SQLite assembly and `describe`, component detail
and `rdeps`: description schema 4; advisor version
`86c5a834fec0244e3d6232268b16243dedd9d7f69e9eb95e41ba59dc17bf58a5`;
the request/advice ports and `advisor` mailbox alias above; no reverse dependents.
This verifies the standard definition, not live application capabilities.

N5's `_qualification_write_graph.py` and `_qualification_write_assembly.py`
require the literal empty seed, target and `n5-write.txt`; preserve their bytes.
`codex_host.write_operator_provider` is reusable construction, not qualification.
A new injection root must import the pinned repository base into private
`GitAuthority`, assemble one journal/authority/launcher and use its own target
and capabilities. The trusted checker compares the entire immutable candidate
tree to base, including modes/unchanged blobs; WRITE is not a path guarantee.

Use `/usr/bin/python3 -I`, fixed inline check programs and stdlib in the pinned
runtime. `runtime_plan` supplies Python/Git; `controller_closure` excludes dev
groups and establishes no pytest/ruff availability.
Bind instruction, path, matrix, mutations, wrapper, base and definition source
in application identity. Gate/runtime, workspace and native revisions derive
from their actual factories; never guess them or reuse historical g8 pins.

## The exam is independent of the proposed tests

A fixed trusted program independently checks the target's acceptance/refusal
matrix and relevant refusal-guard mutations. It imports only the base-pinned
target, not the candidate test module, and uses its own assertions. Each mutant
has an exact once-occurring source target, an explicit replacement, and a
specific assertion that fails under it. Syntax/import errors, timeouts and
infrastructure failures are NOT PROVEN, never kills. This proves the exam
detects the weakened policy and that the unchanged target satisfies it.
Mutants and runner files live in private `/tmp` scratch, never the READ
snapshot or authority; each variant runs in a fresh bounded contained process.
The fixed program must positively exercise permitted input, not only refusals.

Running the proposed unittest suite is a separate useful check. A trusted
wrapper selects exactly this file, asks discovery for a positive case count,
refuses zero tests/skips/errors/failures and requires complete process exit.
It also runs the same proposed suite against each fixed mutant and records
observed assertion failures separately from errors. Normal unittest discovery
must not recurse over the whole existing pytest suite. The wrapper must handle
`-I` deliberately: locating the pinned repository modules is trusted wrapper
work, not a dependency on ambient `PYTHONPATH`.

Arbitrary candidate Python can monkeypatch unittest, fabricate output, exit
early or recognize a mutant. Same-process wrappers/reports/markers cannot
authenticate assertion execution. Containment protects authority, not reports.
The independent oracle proves target policy, not equivalent candidate coverage;
never mint authenticated execution or mutation-kill claims from that report.

Recommended owner decision: keep arbitrary unittest authoring with untrusted
observations and human inspection of exact assertions against the fixed matrix.
Gate claims cover only independent oracle and tree scope; review states that
limit. Spoofing fixtures prove reports never gain independent-proof status,
not that every lie is detectable. Mechanical authentication needs an accepted
restriction on candidate form and trusted execution law, a scope change.
The stronger current #183 criterion is unmet; this decision blocks implementation.

## State when each await resumes

| Boundary | State that may now exist | Required observation/action |
| --- | --- | --- |
| Gate factory's runtime probes | A completed probe or cancelled probe; no run candidate mounted | Join teardown; reject drift or incomplete probe before publishing revision. |
| Provider acquire | Inert handle, or acquisition reply lost after local construction | Walker records/enrolls before materialization; record failure closes inert handle locally. |
| Resource materialize | Durable row and possibly processes, callback endpoint, workspace or gate guard | Existing callback checks run control before exposure; cancellation joins closure, ownership loss relinquishes local custody. |
| Writer's trusted base read | Target may move while the read runs | Compare exact request/base; recheck control before dispatch. The gate later checks current-base identity independently. |
| `executor.execute` | Native output and callback observations; worker descendants must already be quiescent | Require `ExecutorSuccess` and current control; partial/failure/timeout never proceeds to capture. No test claim comes from model prose. |
| `workspace.commit_all` | Stage committed/exported/imported; candidate may already be published although answer was lost | Reuse capture's control checks and atomic external closure fence; require changed exact candidate. Candidate presence alone is not writer completion. |
| Writer completion and cleanup | Checkpoint can be durable before release returns | Restore exact checkpoint on retry; join cleanup. A cleanup failure remains a failure even with a completed checkpoint. |
| Immutable candidate/tree reads | Candidate and target may differ from earlier observations | Check repository, base, entire allowed diff and mode; join trusted worker. No host stage walk. |
| `gate.verify` | Prepared merge, snapshot or a completed/red check; a fenced attestation may already exist | Compare candidate, repository, target, expected base and tested tree; refuse base drift. Gate joins checks/scratch cleanup and checks control before minting. |
| Checker completion and cleanup | Evaluation checkpoint durable; gate acquisition may still need closure | Preserve exact checkpoint; join closure before terminal transition or review park. |
| Advisor `ask` send/reconcile | Durable request may exist, reply may already exist, or reply lands before park | Reuse derived identity and durable effect receipt; missing reply raises `InvocationParked`, never returns placeholder advice. |
| Park/restart/wake | Writer and checker checkpoints plus retained candidate; no live workspace or native process | PARKED wakes only from provenance-valid reply. Reconstructed advisor asks for same request; checkpoints avoid another writer turn or gate. |
| Authenticated reply/domain command | Reply may be committed while command completion is missing | Existing transactional provenance and wake scan handle it; retry replays one fact. |
| Normal close/shutdown/cancellation | Cancellation or ownership loss may latch during joined teardown | Loss has precedence; do not close successor acquisitions. Shutdown abandons without inventing user cancellation. Cleanup failure blocks terminal transition. |

Writer completion closes with `release`, retaining its ref and removing mutable
payloads. Later advisor parking holds only a mailbox: no writer workspace or
process. Checker failure cannot retroactively discard that released candidate.
Failed/cancelled writer attempts discard; successor recovery uses existing
rows/fences. Counterfactual acquisitions discard independently.

Later operator disposition of released review artifacts is separate; no pruning
command is proposed. A retained candidate after checking failure is unreviewed.

## Credential-free implementation evidence

The fake path executes the same graph with genuine controllable doubles.
Substitute platform launch primitives so lifecycle assertions run on Windows;
native Linux checks separately prove real capture/gates/runtime. Skips are
unmeasured physical evidence.

Required scenarios include a correct one-file contribution through authenticated
review; no change; unrelated edit; wrong mode/path; executor partial/failure;
red, timed-out or overflowing gate; zero tests; fabricated suite reports;
assertion-killed and merely erroring mutants; candidate/base drift; cooperative
cancellation and owner loss at materialization, model return, capture publication,
gate completion and joined cleanup; death after checkpoint before close; review
park and process restart; fast reply before park; reply committed before command
completion; and duplicate/conflicting reply keys. Assertions inspect candidate
and target refs, checkpoints, receipts, authenticated reply provenance, capability
accounting and physical teardown facts where measured. An empty fault list or
unchanged target alone cannot prove that the writer/checks ran.

No merge adapter is supplied; target remains at base. Operator publication,
installation, fresh exact-profile qualification, authenticated startup and
bounded live-task authorization are separate gates. ADR 0021 leaves vendor
identity unverified; N5 g6/g8 is not current availability/authorization.
Claude/Pi and M8 closure remain separate.

## Decision before implementation

The owner must accept independent oracle plus human coverage review, or require
a reviewed restriction on candidate test form. Acceptance names the reviewed
draft/head and revises the stronger issue criterion explicitly.
Technical scope: failed checking fails the run with retained writer/check
evidence; only passing independent checks reach the advisor. Pin deadlines,
file/case/output bounds and mutation bytes in implementation identity. Preserve
existing released-candidate retention; add no cleanup effect or implicit repair.
These are proposed assembly details, not additional approval gates. The parent
design record owns acceptance; this draft records feasibility and its limit.

## Fable recommendation and disposition

At the owner's request, a tool-free advisory from `claude-fable-5-1`
(`job_00578a61b6ba`, 2026-10-14) recommended ordinary unittest authoring and
human coverage review, not a bespoke assertion format. It did not inspect
the repository or qualify implementation. Its recommendation is not owner
acceptance of the changed evidence contract.

For the next revision, prefer one fixed broken-target observation over a full
candidate mutation campaign. A passing ordinary run and an assertion failure
against the broken target are useful observations, not authenticated coverage.
Establish the fixed target/oracle behavior during implementation verification;
do not repeat the unchanged oracle campaign for each candidate or add a new
persistent evidence cache. This simplifies the proposed exam above, conditional
on the owner's evidence-strength decision.

Fable also suggested a small AST allowlist. Do not adopt its estimated size or
treat an import/call denylist as an execution guarantee: Python permits indirect
behavior. Such checks could only be explicitly limited lint, not an independent
proof. No AST interpreter, restricted language or new lint subsystem is selected.

Automated success would mean exact allowed tree change plus bounded reported
test observations. Human acceptance would mean authenticated review of the
exact candidate's assertions and useful cases. Graph completion would mean
delivery of that candidate, observations and authenticated advice, including
negative advice; it would not itself mean human acceptance or installation.
