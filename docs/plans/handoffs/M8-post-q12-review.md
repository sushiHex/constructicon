# M8 maintenance: the post-q12 timebox review

Under [#186](https://github.com/sushiHex/constructicon/issues/186). The owner's q12 authorization set a timebox: "if q12 is not accepted, live attempts pause and the task, model and exam design are reviewed". q12 was not accepted. This document is that review. It is a proposal. It authorizes no VM start, resume, retry, credential use or repository setting. Each decision in it takes effect only when the owner records it on #186; the owner's comment is then quoted in [Decision](#decision).

Two reviewers decided each question independently from the same brief: Astra (`gpt-6-astra`, hardline) and Fable (`claude-fable-5-1`). The orchestrator checked their factual claims against source and reconciled the points where they disagreed. Where this document departs from either reviewer, it says so.

## The record

These are the live sessions on #186, from the stated cause in each session's own report. q12's cause is from [#226](https://github.com/sushiHex/constructicon/issues/226).

| Date | Session | Reached | Outcome | Class |
| --- | --- | --- | --- | --- |
| 2026-10-14 | First maintenance session ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6167500461)) | P2 | An unlisted `cp` warning on stderr, despite exit zero and the marker | Contract |
| 2026-10-14 | g9 continuation ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6178498401)) | P8 | Exit 1; the custody refusal was later diagnosed ([inspection](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6179145194)) | Code defect |
| 2026-10-15 | g10 private continuation ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6182038551)) | C10 | `application-not-accepted` | **Application** |
| 2026-10-15 | Diagnosis, first attempt ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6183496149)) | D0 | A missing PowerShell parameter in the operator's transport | Operator |
| 2026-10-15 | Read-only diagnostic ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6186507897)) | D4 | Completed: g10's writer recorded `capture-mismatch` | Diagnostic |
| 2026-10-15 | g11 ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6201449870)) | C3/S4 | The lane's own JSON summary on stderr broke a blanket empty-stderr rule | Contract |
| 2026-10-17 | q12 ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6232755291)) | C1 | The drift tool's real no-drift line differs from the declared `NO DRIFT` | Contract |

**The application was tested once, in g10, and not since.** g10 ended in a normal non-acceptance. Its writer recorded `capture-mismatch`, and a credential-free reproduction showed that an executor making no change reaches the same refusal ([implementation record](M8-implementation-record.md#capture-refusal-diagnostics-after-retained-outcome-diagnosis-refs-186)). Neither g11 nor q12 reached the application, so q12 says nothing about the model. An earlier summary on #226 recorded "application untested"; that was wrong, and [a correction is posted there](https://github.com/sushiHex/constructicon/issues/226#issuecomment-6238582127).

**Three of the seven stops are one class:** an exact output expectation that was never traced to the code that emits it.
- P2 assumed `cp --no-clobber` is silent on the host.
- g11 required empty stderr from a lane whose own source writes a summary line there ([lane output](M8-maintenance-lane-output.md)).
- q12 declared a paraphrase of the drift tool's line. The real line had been public since the R6 completion comment on #73, of 2026-10-09. The authorizations and later reports shortened it to `NO DRIFT`, and the procedure copied the shortened form.

The rehearsals did not catch any of the three, because each one stubbed the emitter with the same assumption ([#189](https://github.com/sushiHex/constructicon/issues/189)).

## What it costs

A live session has cost one reviewed procedure of about 1,000 lines (q12's is about 1,100), its rehearsal, a Codex pass, CI, and an owner go. Six sessions in four days produced one application outcome. Neither reviewer could put a number on the owner's attention, which is the scarcest input.

Astra raised the question nobody had asked: what the experiment is for. The contribution under test is one bounded data file, judged against eight fixed mutants ([implementation record](M8-implementation-record.md)). There are two possible goals:
- getting that contribution;
- showing that the whole control system runs autonomously.

They price differently. Without a stated goal, every safe refusal justifies another procedure, and the experiment has stop rules but no stopping condition.

## Proposed budget

| Budget | Limit | Stop rule |
| --- | --- | --- |
| Live sessions | **One**, q13 | Any stop on an exact output expectation ends that approach for host-tool lines. They then become exit-status checks, with the output recorded privately and not compared. A new design follows before any further session. |
| Application attempts | **One**, inside q13 | A dispatched or uncertain dispatch consumes it. A second normal non-acceptance reopens the task, model and exam before any third attempt. |
| Procedure preparation | One q13 document and its rehearsal | If q13 needs a second procedure correction before its go, reassess first. |

Astra proposed one session and one attempt. Fable proposed two of each, with the class stop rule above. This review takes Astra's numbers and Fable's rule. g10's outcome is indistinguishable from an executor that changed nothing, so another attempt with nothing else changed teaches little.

Before q13's go, the owner answers two questions:
1. **The goal:** the contribution, or autonomous operation.
2. **The no-op question:** does this model, at this effort, change the fixed task at all? Fable proposes answering it offline: run the task prompt on the workstation, outside the executor and the custody store, with no VM. Whether [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md) permits that is the owner's call. This review raises it and does not recommend it.

These limits are management limits. They do not bound cleanup, and custody waits can be unbounded ([session](M8-maintenance-session.md)).

## q13 preparation

Source-only work may start during the review. Nothing below needs the VM.
- **An in-step drift check.** It runs on the host before the next command and compares status, stderr and the whole stdout against the expected bytes, final LF included. Only then does it print the repository-owned `drift-checked`. T5 checks a step only after the whole step has run, so the check has to sit inside the step ([#226](https://github.com/sushiHex/constructicon/issues/226)).
- **The expected bytes go in through `--values`.** They are filled by the packager's existing values mechanism as a `readonly` placeholder (`scripts/m8_procedure_package.py:30-36`). The repository holds the placeholder, and the private values file holds the bytes.
- **A count lint.** A built step's drift-tool invocations must equal its declared drift placeholders. That would have refused all nine q12 steps that declare `NO DRIFT`.
- **The [#189](https://github.com/sushiHex/constructicon/issues/189) rule.** A test stub of a host-only tool is labelled measured, citing private evidence, or synthetic. A synthetic stub is paired with a case where a different plausible output fails the step. Success paths assert empty stderr wherever the contract says so.

The full q13 procedure and its go request wait for the decision below.

**The expected drift line.** The owner approves it by digest:
1. The orchestrator writes the one-line expectation to a private file and reports its SHA-256.
2. The owner compares the file with the #73 R6 completion comment and replies with the digest.

The line has two independent observations, #73's and q12's private capture, and the orchestrator has checked that they are byte-equal. A model does not approve it. Model-written paraphrases are how `NO DRIFT` entered the record. Here this review follows Fable; Astra would have allowed approval under explicit delegation.

**Two gaps nobody had raised:**
- **The drift tool is not in the repository.** Nothing checks its digest, so a modified tool that prints the approved line passes every proposed check. q13 should pin the tool's digest in its guard, and a later slice could bring its source in as a reviewed file.
- **The q12 captures have no retention rule.** They are the only measurement of the line, and the #189 rule needs a stable private identifier to cite for measured stubs.

## Public-text work

These items run alongside the review and do not depend on it.
- **#229:** the scanner refuses every redirect, so the token never leaves `api.github.com` ([PR #231](https://github.com/sushiHex/constructicon/pull/231)). Both reviewers put it first. The `gh` session the agents use carries the `repo`, `workflow` and `delete_repo` scopes, so a leak of it would compromise the repository.
- **The backfill:** this runs after #231, with a fine-grained token the owner mints, read-only, scoped to this repository alone, expiring in one day.
  - It adds a pass over all reachable history with no date filter. `--since` filters branch commits by date (`scripts/ci/check_public_text.py:436`).
  - It records as a gap any force-pushed head that no longer resolves; the activity listing holds 25 force pushes.
  - `PUBLIC_TEXT_SWEPT_THROUGH` advances to the run's start, and only after a complete run.
- **[#230](https://github.com/sushiHex/constructicon/issues/230):** a tag ruleset that restricts creating, updating and deleting tags, with no bypass actors, admins included. The sweep should also report any existing tag as a finding.
  - **Why not the events API:** Fable measured it. Its newest event lagged the activity listing by about 19 hours, and 300 events covered about 17 hours, not 2.5 days.
  - **Why no bypass:** every agent acts as the owner's account, so "only write-access holders" restricts nothing.

## Owner actions

1. Record the budget and the goal (one comment on #186).
2. Rule on the no-op question.
3. Approve the drift expectation by digest.
4. Rule on the #73 comment, which publishes raw host output: declare that line non-private, or delete the comment. An edit keeps the old text in its history.
5. Approve the tag ruleset.
6. Mint the backfill token.
7. Later, give a fresh go on an exact q13 commit.

## Decision

Pending the owner's comment on #186.
