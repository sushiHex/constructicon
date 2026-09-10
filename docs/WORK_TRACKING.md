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
3. Before merge, require the repository gate and CI on the exact head, relevant
   native/mutation/compatibility proofs, and independent review with no
   unresolved blockers. State checks not run and why; Windows skips are not
   physical proof. Docs-only validation includes links, archive digests, and
   truthful source/status claims; a green baseline is not new behavior proof.
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

## Keep the system small

No Project board is required today. Add one only when a shared prioritization
view earns its maintenance cost, using existing issues rather than parallel
draft tasks. Keep status in one place; do not mirror it with labels, board
fields, and a checked-in list. No custom synchronization service is needed.

Accepted exclusions stay in the decision/implementation records until a
concrete, newly authorized proposal needs tracking. Do not reopen rejected
connector liveness or reinterpret retained history merely to fill a backlog.

This guide describes the workflow, not which task is currently next.
