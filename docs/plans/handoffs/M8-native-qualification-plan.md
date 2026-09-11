# M8 native qualification: bounded investigation plan

Status: investigation scope authorized by the owner's request to implement
the four recommended next steps, 2026-09-11. This is not a successor ADR,
native-auth approval, or a production availability claim.

Base: `8a2da8de653b919e492558eafb921d973e7535eb`, the squash merge of PR #50.
Its tree is identical to reviewed head `375ffa2783b3fa59b12ce4ce9f31c7db1dae23c7`.
GitHub [#37](https://github.com/sushiHex/constructicon/issues/37) owns work state;
[#38](https://github.com/sushiHex/constructicon/issues/38) owns the eventual
authentication decision. This file fixes scope and acceptance, not a backlog.

## Authority and hypothesis

[INVARIANTS](../../INVARIANTS.md), [ARCHITECTURE](../../ARCHITECTURE.md), and
[ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md)
remain authoritative. The approved M8 milestone plan stays byte-identical.

PR #50 proved a bounded result: the supported startup catalog removes native
patch and selected model-dependent tool surfaces on the pinned binary, while
the contained callback succeeds. It did not prove complete startup control,
journal-driven native recovery, native-home or descendant ownership, or
revocation. Its serialized fixture leases cannot stand in for journal rows.
See the [measured record](M8-native-mediation-probe.md).

Test the next hypothesis: a fresh, completely controlled startup combined with
the existing acquisition lifetime can bound one native invocation, without
introducing a second scheduler, lease ledger, or resumable native conversation.
One pinned Linux CLI, the same two model profiles, and credential-free local
Responses fixtures remain the scope. The binary and catalog pins from PR #50
do not change. No real provider, login, account data, billing, deployment, or
desktop configuration participates.

The existing `ExecutorGrantPolicy` admits only `none` and
`provider_route_only` network access. `ExecutorLaunchIdentity` requires a
route identity for the latter. A broader native harness is neither. Do not
publish a production profile, fake a route conformance identity, or change
the wire schema to make an experiment assemble. A test-only composition may
exercise `LeasedCapability` and the journal without claiming executor-profile
qualification. Any eventual policy/version change belongs to the proposed
successor decision, after evidence, not this implementation.

## Slice A: controlled startup

Read the exact tagged upstream loader, app-server entry point, and tool
registration sources. Inventory configuration and startup inputs by origin:
system/managed, user/profile, working-directory/ancestor/repository,
environment, hooks, skills/plugins/MCP/apps, and runtime/model metadata.
Distinguish release-supported controls from debug-only overrides. A generated
schema or an empty observed tool list alone does not establish the inventory.

The candidate gives the native harness its own fresh home and working
directory, never the acquired repository as its working directory. Only the
contained worker receives that repository. Configuration, model selection,
catalog bytes, environment and protocol requests come from the controller;
model arguments cannot choose them. Reject an uncontrolled startup input
before launching, rather than auditing a side effect afterward.

For each claimed control, exercise a positive control and its refused or
isolated counterpart. Use inert markers and public canaries, no external
services. Preserve actual native wire inventories for both selected models.
Record warnings, refusal timing, unexpected startup processes and provider
requests. Configuration precedence is observed on the pinned release, not
inferred from a development-only flag or a different binary.

Acceptance requires an origin-to-control-to-test inventory. Every origin is
either controlled with evidence or explicitly unqualified. Re-run the native
patch/image/model-dependent controls under the candidate startup. If an
uncontrolled origin can change authority or execute before validation, stop
this recipe and record the exact source and reproduction. Do not append an
open-ended denylist or weaken the claimed boundary.

## Slice B: durable lifecycle composition

Start only after Slice A has a supported recipe with no unresolved startup
authority gap. Keep it a separate reviewable change. Reuse:

- `LeasedCapability`, `AcquiredCapability`, `LeaseContext` and
  `StaleAcquisition` from `core/workspace.py`;
- the existing lease/acquisition identity derivation and Git acquisition
  guard/closure law;
- `SqliteJournal`, ordinary capability-lease rows, `ControlPlane` and
  `RunHost` recovery;
- the existing Linux namespace supervisor for physical descendant ownership,
  if its actual interface can serve the native composition without changing
  the accepted boundary.

Acquire inertly; record and enroll cleanup before materialization. Native
home, private protocol resources and all later allocations must belong to the
recorded acquisition or its physically owned ephemeral namespace. Recovery
derives its inventory from SQLite, never from a report pipe or supplied rows.
No PID, native thread/session id, or fixture marker becomes durable authority.

Use two real interpreters over the same journal and authority. Exercise owner
death after record/before materialization, during materialization, with a
native turn and worker active, after native completion/before checkpoint, and
after checkpoint. Observe old resources before recovery; start a fresh
ControlPlane and let its RunHost perform actual reclaim and reconciliation.
Check retained checkpoint behavior, epoch advance where appropriate, exact
lease closure, and no stale native invocation or home reused by the successor.

Prove cancellation and stale-epoch revocation separately from process exit.
An old participant must be unable to start further work after closure; a
blocked or failed cleanup cannot report disposal. Include a descendant that
changes session/process group, so one PID or process-group kill cannot pass
as complete ownership. Assertions about reaping need actual reaping evidence;
a zombie is only non-executing. Failure cleanup is bounded, retains the
original failure, and is never credited as measured automatic recovery.

The current `LinuxLauncher.run` accepts a bounded, complete stdin buffer; the
native app-server driver uses a duplex conversation. Inspect that mismatch
before adding plumbing. Do not copy a reaper, invent a process manager, widen
the worker's network authority, or call a modified recipe the existing proof.
If a new launch/transport contract, durable field, or trust boundary is needed,
record the specific missing contract and stop at the decision boundary.

## Evidence and stopping rules

Each code slice requires the repository gate, exact-head CI, relevant native
proofs, assertion mutants for its new guarantees, and independent review with
no unresolved blockers. Windows skips are not Linux evidence. Inspect the
downloaded exact-head native artifact separately from test assertions.

Record four distinct outcomes for every claim: proved at the stated scope,
refuted by a reproduction, unexecuted, or blocked by a named prerequisite.
An expected refusal can pass its regression while refuting qualification.
Retain failed hypotheses and corrected observation assumptions honestly.

Stop rather than substitute if proof needs account access, credential
emulation, a modified native binary, a host-policy relaxation, an unapproved
network/auth schema, or a new persistent authority. A negative startup result
prevents Slice B from borrowing credit from the older lease-level experiment.
An interface/authority blocker is a result to bring to #38, not permission to
implement around an accepted decision.

## Decision packet

After the executed proof, update the living authentication/evidence records
and #38 with exact heads, reproduction commands, source pins, pass/refusal
matrix and remaining prerequisites. Do not rewrite this plan to match results.

Only a positive combined result warrants a proposed successor ADR naming the
precise ADR 0018 clauses, trusted code, network/grant version compatibility,
revocation, recovery, live-account conformance gates and revised slice order.
It remains proposed until the owner accepts it. A partial or negative result
leaves native authentication unavailable and names the next required decision.
No paid gateway is substituted for subscription reuse. Claude Code, Pi,
OpenRouter and M9 remain outside this bounded investigation; the task-shaped,
provider-neutral executor seam stays unchanged.
