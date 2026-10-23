# Tracking work

GitHub Issues owns current work state. Repository plans and accepted ADRs own
design intent and decisions; PRs and living implementation records carry
completion evidence. Do not maintain the same backlog in Markdown or a chat.

Start with [open issues](https://github.com/sushiHex/constructicon/issues),
[ready work](https://github.com/sushiHex/constructicon/issues?q=is%3Aissue%20is%3Aopen%20label%3Aready),
or [milestones](https://github.com/sushiHex/constructicon/milestones).
An issue, label, assignment, or milestone never overrides
[INVARIANTS](INVARIANTS.md), [ARCHITECTURE](ARCHITECTURE.md), or an
[accepted ADR](adr/README.md). A proposal is not approved because it is tracked.

## One work item, one issue

Search open and closed issues and active PRs before creating work. Use the
[issue forms](https://github.com/sushiHex/constructicon/issues/new/choose):

- **Bug report:** expected/actual behavior, a minimal credential-free
  reproduction, and exact version/environment. Do not label an untested
  hypothesis a confirmed defect.
- **Work item:** one bounded implementation, investigation, or planning
  outcome; scope/non-goals; authority links; prerequisites; observable
  acceptance criteria. A supported negative result can complete an
  investigation without qualifying the proposed feature.
- **Design proposal / decision:** the problem, alternatives and tradeoffs,
  affected contracts/ADRs, and evidence needed for a decision. Record an
  accepted architectural change in a reviewed repository document, not only
  an issue comment.

Use issue numbers as task identities. Small steps may be checkboxes inside the
owning issue; independently assignable work becomes native sub-issues. Use a
milestone for an outcome spanning issues, not another parent checklist with
the same scope. Do not create a new issue for every review comment: keep
in-scope corrections on the PR; track accepted follow-ups separately.

Native **blocked by / blocking** relationships own unconditional issue
dependencies. Explain external prerequisites and conditional choices in the
body; they are not a second manually maintained dependency list. Dependencies
describe sequencing, not enforcement: inspect the blocking issue's actual
outcome before starting. Closed as declined or superseded does not mean a
required proof exists. A milestone is not a delivery date or design approval.

## Triage and ownership

Keep metadata small; reuse the repository's existing bug, enhancement, and
documentation labels. Additional labels have distinct jobs:

| Label | Meaning |
| --- | --- |
| `needs-triage` | Scope, evidence, or authority still needs maintainer review |
| `ready` | The stated work is scoped, accepted, unblocked, and available to pick up |
| `investigation` | The deliverable is evidence, including an honest negative result |
| `decision` | An explicit maintainer/owner choice is needed before dependent work |

New form submissions receive `needs-triage`, never `ready`. Maintainers remove
triage after disposition; work waiting on a decision or external prerequisite
stays open without `ready`. For an investigation, ready means evidence-gathering
is scoped and accepted, not that its possible implementation is approved.
Recheck dependencies and authority even when a label says ready; an agent's
actions must also stay within the active user request.

Assignees identify responsibility, not priority. Ask before claiming existing
assigned work or assigning somebody else. Contributors without assignment
permission can volunteer in a comment. At the start of agreed work, remove
`ready`, record the branch and scope, and open a linked draft PR when useful.
Agents sharing an account should name their branch/session in that comment so
parallel sessions do not duplicate work. Do not use one blanket assignee for
the whole backlog.

If work pauses, leave one concise handoff: branch/head, evidence obtained,
what remains, and the exact blocker or next action. Release/reconfirm ownership
as appropriate. Restore `ready` only if the work is actually available and
unblocked. Issue comments are handoffs and decisions, not raw session logs.

A *pause* hands over in the issue. A delivery PR includes one entry to
`docs/AGENT_HANDOFF.md` that becomes durable on merge: what the slice established,
what it deliberately did not, and any reported fact that turned out to be wrong.
Do not invent a merge SHA before merge or require a follow-up PR to insert it.
That file carries what outlives an issue and holds no open work — the issue keeps
that. Incidental prose corrections do not require a new handoff entry.

## Implement, review, close

1. Read the issue, dependencies, linked plan, and accepted decisions. Inspect
   existing contracts before inventing a primitive. For a small incidental
   docs correction, the PR can be the work record; do not manufacture an issue
   merely to satisfy a template. Substantive work needs its scoped issue.
2. Link the issue from the PR. Use `Closes #<number>` only when merging into
   the default branch will satisfy the whole issue. For partial work use
   `Refs #<number>`; a plan-approval PR closes the decision, not its dependent
   implementation. Closing keywords are interpreted by
   [GitHub](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue),
   not a custom bot.
3. Before merge, apply the [delivery policy](#delivery-policy): selected CI on
   the exact head, risk-relevant proofs and sufficient independent review with
   no unresolved blockers. A second full local suite is not a universal gate.
   State checks not run and why; Windows skips are not physical proof. A green
   baseline is not new behavior proof.
4. Put exact-head evidence in the PR and durable milestone results in the
   living implementation record. Preserve approved plans; update only the
   intended archive digests. Close completed work with the merged PR/evidence.
   Close duplicate, declined, or superseded work with the reason and successor
   link, not a false completion claim. Investigations may close with a negative
   result; remaining implementation needs its own issue.
5. Re-triage newly unblocked issues. Close a milestone only after reconciling
   its intended outcome and all remaining work; a count of closed issues is
   not the acceptance proof.

PR templates and issue forms are prompts, not authorization or automatic gate
enforcement. They also do not replace maintainer review for API-created issues.

## Fresh agent sessions

Query current GitHub state rather than reconstructing it from chat or a cached
TODO. From this repository:

```bash
gh issue list --repo sushiHex/constructicon --state open --limit 100
gh issue list --repo sushiHex/constructicon --label ready --state open --limit 100
gh issue view <number> --repo sushiHex/constructicon --comments
gh api --paginate repos/sushiHex/constructicon/issues/<number>/dependencies/blocked_by
gh pr list --repo sushiHex/constructicon --state open --limit 100
```

Issue lists are bounded; narrow the query or paginate if the backlog exceeds
the limit. If GitHub is unavailable, report that current ownership/status is
unverified. Do not create a replacement backlog or treat a cached label as
permission to start conflicting work. A review/status request alone does not
authorize posting, assignment, or other external changes.

## Delivery policy

This is the single binding delivery policy for every Codex, Claude Code,
subagent and contributor session. It replaces routine duplicated verification,
not the invariants, accepted decisions, explicit owner restrictions or required
repository checks. A stricter task-specific requirement still applies; record
why it applies rather than generalizing it into a new universal gate.

### 1. Match verification to risk

Before implementation, state the observable delivery outcome, risk tier and
smallest relevant proof set in the issue or PR. Use the highest applicable tier;
small diffs can carry consequential risk. Do not create a separate plan document
for a routine change solely to state these three facts.

| Tier | Scope | Required evidence |
| --- | --- | --- |
| Prose | Non-executable documentation, status or wording only | Links, applicable archive digests, and focused factual review. No full local suite or mutation run. |
| Code | Ordinary implementation, tests, dependencies or tooling | Affected tests locally, accepting and refusing cases for changed behavior, and the full code CI gate on the final candidate. |
| Consequential | Authority, credentials, containment, custody, durable state, concurrency, evidence acceptance or merge-gate selection | Code-tier evidence plus independent review of the affected boundary and relevant physical, interleaving, compatibility or mutation proofs. |

Runnable instructions, extracted fixtures and executable configuration are not
prose merely because they are in Markdown. Run their affected tests and review
the command boundary before execution. CI path classification is an optimization,
not authority to understate the semantic tier or skip an explicitly required proof.

During iteration, run focused tests. Do not repeat the full local suite after
each edit. Exact-head full CI is the default broad code gate; a second full local
run requires a stated diagnostic or platform reason. Use targeted Windows tests
for Windows boundaries, not a blanket full Windows run alongside Linux CI.
Platform skips are not physical evidence. The trusted-base classifier gives the
docs fast path only to its explicit prose/status allowlist; runnable handoffs and
unknown paths retain full CI. Docs-only CI must positively validate links and
archive digests in the proposed merge tree rather than silently pass. Expanding
that allowlist is a consequential change, not an author's label or opt-out.

For changed safety gates, choose mutants that exercise distinct failure modes
and use inputs where bounds actually bind. Do not add redundant mutants merely
to increase a count. Run affected inventories locally when needed; existing
required CI inventories remain enforced. Missing/erroring tests are not proof.
Do not introduce a generalized test-selection framework to optimize one change.

Freeze a coherent candidate before expensive verification. A later code change
requires fresh applicable CI; a local focused rerun covers the affected behavior.
Do not rerun unchanged manual proofs for prose-only follow-ups: compare the
relevant source/test blobs and retain the original tested revision explicitly.
Required final-head CI must still pass; never relabel old results as new runs.

### 2. Review once meaningfully

One independent, risk-appropriate review is sufficient. It may be a human,
another agent, or the connector; self-review alone is not independent review.
For consequential work, the review must inspect the relevant authority,
interleaving and evidence assumptions, not just summarize the diff. Delegate
routine checks to lower-cost models and reserve high effort for these boundaries.

Reproduce findings, fix their class and review consequential fixes narrowly.
Do not automatically restart broad reviews or commission multiple reviewers
after a clean, sufficient review. Wording-only changes need factual checking,
not another adversarial implementation pass. Record the reviewed revision and
any later delta; a materially changed boundary needs a fresh focused review.

Mark PRs ready once implementation and the selected local checks are complete;
run connector review and CI in parallel. Ready for review is not ready to merge:
the selected final-head CI and sufficient review must both finish before merge.
Trigger the connector once; do not repeatedly request the same review while it
is pending. If the connector fails, reports unavailable,
or remains pending 30 minutes after its recorded trigger, it may be replaced by
an independent review covering the final head. An already completed independent
review counts when it covers that head; do not commission a duplicate. Record
the connector status/time, substitute reviewer, revision, scope and findings in
the PR. This is a review fallback, never a claim that the connector completed.

Before merge, reread discussion, reviews and inline conversations, including any
late connector response. All actionable findings must have a verified disposition
and review threads must be resolved. The fallback does not bypass required checks,
required approvals, rulesets or owner authorization. If GitHub still requires the
unavailable check, report that blocker; do not bypass it. A substantive late finding
after merge must be triaged as a regression, not discarded because the PR closed.

### 3. Batch delivery and evidence

Keep implementation, regression tests and durable evidence in the same PR where
possible. Include the handoff entry in that PR without inventing a future merge
SHA. Use the PR for final CI receipts that arrive after the commit; do not make
a second docs-only closure PR just to restate that the first merged. A separate
record is justified by genuinely new live evidence or a substantive correction.

Keep one issue as the work ledger. A PR needs a concise outcome, tier, proof set,
review disposition and remaining limits, not repeated chronological transcripts.
Do not create extra research documents, helpers or issues for every minor step.
Frozen artifacts remain unchanged; refresh only the intended living manifest
entries from staged blobs. Existing in-scope deficiencies are addressed on the
same PR; unrelated improvements stay deferred unless they block delivery or safety.

### 4. Optimize for the delivery outcome

Keep one active delivery objective, with parallel work only where it advances
that objective independently. Before adding a helper, test, review or document,
identify the concrete delivery uncertainty it resolves or the consequential
boundary it protects. If it does neither, defer it. Prefer existing components
and the smallest correct design over new general-purpose infrastructure.

Test the real boundary that failed: for example, actual subprocess argument
transport rather than only string construction. Stop repeating a nondiagnostic
live run; define a new bounded evidence question first. This does not relax live
host custody, exact installation, credential, deployment or model-call authority.

Progress reports lead with working behavior, the remaining critical-path blocker
and the next action. Test counts, mutation counts and merged PRs are supporting
evidence, not delivery milestones. When a gate blocks, diagnose it or use the
defined review fallback; do not replace the objective with unrelated hardening.
Measure critical-path time and useful defects found before adding more process.

## Keep the system small

No Project board is required today. Add one only when a shared prioritization
view earns its maintenance cost, using existing issues rather than parallel
draft tasks. Keep status in one place; do not mirror it with labels, board
fields, and a checked-in list. No custom synchronization service is needed.

Accepted exclusions stay in the decision/implementation records until a
concrete, newly authorized proposal needs tracking. Do not reopen rejected
connector liveness or reinterpret retained history merely to fill a backlog.

This guide describes the workflow, not which task is currently next.
