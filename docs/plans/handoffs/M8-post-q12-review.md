# M8 maintenance: the post-q12 timebox review

Under [#186](https://github.com/sushiHex/constructicon/issues/186). The owner's q12 authorization set a timebox: "if q12 is not accepted, live attempts pause and the task, model and exam design are reviewed". q12 was not accepted, and this document is that review.

It is a proposal. It authorizes no VM start, resume, retry, credential or model use, or change to repository settings. Each decision in it takes effect only when the owner records it on #186; that comment is then quoted in [Decision](#decision).

The owner named two reviewers, and each decided the questions independently from the same brief: Astra (`gpt-6-astra`, through hardline) and Fable (`claude-fable-5-1`). The orchestrator checked their factual claims against source and settled the points where they split. Each reviewer then attacked a draft of this document once. Where it departs from either reviewer, it says so.

Step names are the procedures' own prefixes: P for the [maintenance session](M8-maintenance-session.md), C for a continuation, D for the [diagnosis](M8-maintenance-diagnosis.md), and S for a lane boundary inside a C step.

## The record

The table selects the live sessions reported on #186, with each one's cause as its own report states it. q12's cause comes from [#226](https://github.com/sushiHex/constructicon/issues/226). The selection is not an exhaustive count. "Class" names either a procedural cause or an observed outcome; it is not a uniform taxonomy of root causes.

| Date | Session | Reached | Outcome | Class |
| --- | --- | --- | --- | --- |
| 2026-10-14 | First maintenance session ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6167500461)) | P2 | An unlisted `cp` warning on stderr, despite exit zero and the marker | Output contract |
| 2026-10-14 | g9 continuation ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6178498401)) | P8 | Exit 1: preparation left permissions that custody correctly refused ([record](M8-implementation-record.md)) | Code defect |
| 2026-10-14 | g9 custody inspection ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6179145194)) | Completed | It classified the P8 refusal from the retained evidence | Diagnostic |
| 2026-10-15 | g10 private continuation ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6182038551)) | C10 | `application-not-accepted` | **Application** |
| 2026-10-15 | Diagnosis, first attempt ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6183496149)) | D0 | An improvised inline address lookup failed at the Windows shell-quoting boundary before SSH; D1-D3 did not execute | Operator |
| 2026-10-15 | Read-only diagnostic ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6186507897)) | D4 | Completed: g10's writer recorded `capture-mismatch` | Diagnostic |
| 2026-10-15 | g11 ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6201449870)) | C3/S4 | The lane's own JSON summary on stderr broke a blanket empty-stderr rule | Output contract |
| 2026-10-17 | q12 ([report](https://github.com/sushiHex/constructicon/issues/186#issuecomment-6232755291)) | C1 | The drift tool's real no-drift line differs from the declared `NO DRIFT` | Output contract |

**The application ran once, in g10.** g10 ended in a normal non-acceptance whose cause is unresolved. Its writer recorded `capture-mismatch`, and a credential-free reproduction showed that an executor making no change can reach the same refusal ([implementation record](M8-implementation-record.md#capture-refusal-diagnostics-after-retained-outcome-diagnosis-refs-186)). That shows a possible path. It does not show that g10's executor made no change.

Neither g11 nor q12 reached the application, so q12 says nothing about the model. An earlier summary on #226 recorded "application untested". That was wrong, and [a correction is posted](https://github.com/sushiHex/constructicon/issues/226#issuecomment-6238582127).

**Three stops were output-contract mismatches, each with a different test gap:**
- **P2:** the session met unlisted `cp --no-clobber` warnings. Its accepting test used real copying but never asserted stderr (`tests/test_m8_maintenance_session.py:178-209`; [record](M8-implementation-record.md)).
- **g11:** the procedure required empty stderr, although the lane writes a JSON summary there (`src/constructicon/substrate/executors/codex_lane.py:861-865`; [lane output](M8-maintenance-lane-output.md)). Its lane doubles did not reproduce that summary (`tests/test_m8_maintenance_g11_continuation.py:535-547`).
- **q12:** the procedure declared `NO DRIFT`, and its rehearsal's drift stub printed exactly that (`tests/test_m8_maintenance_q12_rehearsal.py:133`). The tool's real line had been reported on #73 on 2026-10-09. The authorizations and later reports shortened it to `NO DRIFT`, and the procedure copied the shorter form.

The common lesson: validate the whole output contract against its actual emitter, or against identified measurements, before declaring it. [#189](https://github.com/sushiHex/constructicon/issues/189) audits the older tests for the same gaps.

## What it costs

The q12 procedure alone is 1,096 lines. Each session also needed a rehearsal, a review, CI and an owner go. This review has no measured preparation cost per session and no measure of the owner's attention. The eight sessions above produced one application outcome.

The contribution under test is one bounded data file, judged against eight named mutants (`M8-implementation-record.md:5694-5702`). Astra asked what the experiment is for. There are two possible goals:
- getting that contribution;
- showing that the whole control system runs autonomously.

They price differently. Without a stated goal, every safe refusal can justify another procedure.

## Proposed budget

| Budget | Limit | Stop rule |
| --- | --- | --- |
| Live sessions | **One**, q13 | A stop caused by an output-contract mismatch ends the session and triggers a contract review before another session is proposed. No check is removed automatically. A replacement must establish which facts exit status proves and keep the remaining required checks. Implementation and live execution each need their own reviewed authorization. |
| Application attempts | **One**, inside q13; g10 was the first | A dispatched or uncertain dispatch consumes it. A second normal non-acceptance reopens the task, model and exam before any third attempt. |
| Procedure preparation | One q13 document and its rehearsal | If q13 needs a second procedure correction before its go, reassess first. |

Astra proposed one session and one attempt. Fable proposed two of each, with a stop rule limited to host bytes that no reviewed fence or measured capture declared. This review takes Astra's numbers, for two reasons:
- **Attempts:** a second attempt that changes nothing else and answers no diagnostic question teaches little. The capture path has changed since g10 (`M8-maintenance-q12-continuation.md:787`), so whether anything else changed is itself open.
- **Sessions:** every session needs its own owner go on an exact commit anyway, so a budget of two would authorize nothing more. A second session, if q13 stops, costs one comment on #186 rather than a new review.

The stop rule is Astra's form. Fable's narrower rule would have weakened host-tool checks automatically; Astra's requires a review and removes nothing. Fable accepted the one-and-one budget given the session reason above.

Before q13's go, the owner answers two questions:
1. **The goal:** the contribution, or autonomous operation.
2. **A diagnostic for g10:** would a separately scoped run help tell model behaviour apart from executor or capture behaviour? Fable proposes running the task prompt on the workstation, outside Constructicon. Such a run is not necessarily offline. Any credential or model use needs its own authorization. It also cannot establish the inside-graph outcome that [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md) requires, and any departure from accepted execution or custody requirements needs an explicit successor design decision. This review neither recommends nor authorizes the run.

These limits are management limits. They do not bound cleanup, which has no overall wall-clock bound ([session](M8-maintenance-session.md)), and an active-custody lock wait has no bounded duration ([lane output](M8-maintenance-lane-output.md)).

## q13 preparation

The orchestrator proposes to start the source-only items below during the review. None of them touches the VM, a credential or a repository setting.
- **An in-step drift guard.** It runs on the host before the step's next command. It requires status 0, empty stderr, and the whole stdout byte-equal to the expected bytes, final LF included. Only then does it print the repository-owned `drift-checked`.
  - Under `set -Eeuo pipefail`, a nonzero drift verdict already stops a step. The tool's statuses are reported on #73. So the guard adds protection for one case: exit 0 with unexpected bytes. T5 alone would catch that case only after the whole step had run.
  - The expected bytes must travel to the host inside the private package.
- **A typed drift value for `--values`.** Today `--values` accepts only a preview digest, a run ID and a boot UUID, each of a fixed shape (`scripts/m8_procedure_package.py:187-213`). It needs a typed, bounded, shell-safe representation of the exact expected stdout bytes, final LF included, decoded with validation and assigned read-only. This is new implementation work. The repository holds the placeholder, and the private values file holds the bytes.
- **Guard coverage.** Nine q12 steps declare `NO DRIFT`, across ten drift-tool call sites. Every executable call must go through the approved guard, and an unguarded call is refused. Counts are only a cross-check: they prove neither that the expected bytes are right nor that the check comes before later commands. Tests cover C5's conditional call and C11's two calls.
- **The #189 rule.** A test stub of a host-only tool is labelled measured, citing private evidence, or synthetic. A synthetic stub is paired with a case where a different plausible output fails the step. Success paths assert empty stderr wherever the contract says so.

The full q13 procedure and its go request wait for the decision below.

**The expected drift line.** The owner approves it by digest:
1. The orchestrator writes the one-line expectation to a private file. It reports the file's SHA-256, and the private comparison against q12's retained capture.
2. The owner checks the file against that capture and the #73 report, and replies with the digest.

A rendered comment cannot show a final LF, so the capture, not #73, is the byte reference.

This review follows Fable: the owner approves, and a model does not, because model-written paraphrases are how `NO DRIFT` entered the record. Astra counts this as a stricter policy preference, not a technical necessity: explicit delegation plus a byte-preserving comparison would not paraphrase.

**Two further gaps:**
- **The drift tool is not in the repository.** Nothing checks its digest, so a modified tool that prints the approved line would pass every check proposed here. q13 should pin the tool's digest in its guard, and a later slice could bring its source in as a reviewed file.
- **The captures need a durable private evidence reference.** q12 already specifies private capture retention (`M8-maintenance-q12-continuation.md:163-167`, `:752`). What remains is to name a custodian, a retention period, an integrity digest, and a stable private reference that measured stubs can cite.

## Public-text work

These items run alongside the review and do not depend on it.
- **#229:** done in [PR #231](https://github.com/sushiHex/constructicon/pull/231). The scanner refuses every redirect, so the token never leaves `api.github.com`. The agents work through the owner's own credentials, so a leaked token would put the whole repository at risk, not just the scanner's reads.
- **The backfill:** this runs with a fine-grained token the owner mints: read-only, scoped to this repository alone, and expiring in one day. Two scanner changes come first, in their own PR:
  - **A pass over all reachable history, without a commit-date filter.** Today the supplementary branch listing sends `since` to the commits API (`scripts/ci/check_public_text.py:448-459`). The ref-update scan selects updates by their timestamp (`:373-401`).
  - **A recorded gap, rather than a failed run, for a force-pushed previous head that no longer resolves.** Today `compared` fails the run (`:348-371`). The activity listing holds 25 force pushes.

  `PUBLIC_TEXT_SWEPT_THROUGH` advances to the run's start, and only after a complete run. A recorded gap is reported as a gap, never read as coverage.
- **[#230](https://github.com/sushiHex/constructicon/issues/230):** a tag ruleset that restricts creating, updating and deleting tags, with no bypass actors, admins included. The sweep also reports any existing tag as a finding.
  - **Why not the events API:** Fable measured it. Its newest event lagged the activity listing by about 19 hours, and 300 events covered about 17 hours.
  - **Why no bypass:** every agent acts as the owner's account, so "only write-access holders" restricts nothing.

## Owner actions

1. Record the budget and the goal (one comment on #186).
2. Rule on the g10 diagnostic question.
3. Approve the drift expectation by digest.
4. Review the 2026-10-09 #73 comment against the Public text rule (`AGENTS.md:165-168`). Preserve the needed evidence privately, then remove the raw output and its retained revisions; publish only the checked fact. An edit keeps the old text in the comment's history, so removal means deletion. Any exception needs an explicit change to the publication policy.
5. Approve the tag ruleset.
6. Mint the backfill token.
7. Later, give a fresh go on an exact q13 commit.

## Decision

Pending the owner's comment on #186.
