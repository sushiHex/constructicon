# Agent handoff

Durable rules live in [`AGENTS.md`](../AGENTS.md) and
[`INVARIANTS.md`](INVARIANTS.md). Per-slice evidence lives in the living
implementation records under [`plans/handoffs/`](plans/handoffs/). Current work,
ownership and acceptance live in
[GitHub Issues](https://github.com/sushiHex/constructicon/issues), and
[`WORK_TRACKING.md`](WORK_TRACKING.md) governs how a paused slice hands over —
in an issue comment, not here. Query the issues before resuming.

**This document is context, not a parallel task ledger.** It carries what
outlives a single issue: what a slice actually established, what it deliberately
did not, and which reported facts turned out to be wrong. An entry is added when
a slice merges, newest first. Nothing here authorizes work.

---

## N2's first slice — the Codex operator adapter, READ posture

**Merged `919f9e3` (PR #85) on 2026-09-20, base `ae40ed7`. Issue #75 remains
open: its acceptance scope covers READ *and* WRITE, and this is the READ slice.**

The adapter binds ADR 0021's operator-bound route to a real contained process.
Two L1 modules: a pure protocol with no I/O and no launcher import, and a thin
adapter over `LinuxLauncher.exchange`. No credential, vendor account, model call
or network exists in the slice.

**The finding worth carrying: a negative inference is not a positive fact.**
Four review passes found 28 defects, every one reproduced by running code rather
than reading it. Almost all reduced to a single shape. An empty fault list meant
both "the subscription-mode gate cleared" and "the conversation was killed before
recording anything", so a `RecursionError` from an 8 KB nested record published a
turn as `ExecutorSuccess` with the acceptance check never run. An id match meant
both "this is the reply" and "something guessed the id", so a reply emitted
*before* its request satisfied correlation while the session honestly reported a
switch to an API key. A passing test meant both "the behaviour holds" and "the
test never ran" — nine handle tests were gated to Linux and had executed on no
platform at all, and one was silently wrong until CI caught it.

Where the slice now records the fact affirmatively — a `gate_completed` latch set
only after the comparison, ordering over framed *and* framing bytes, a
duplicate-id refusal, a substituted guard that lets a written test actually run —
the class closes. Where it still infers, the limit is written down and pinned by
an assertion.

**Two causes account for nearly all 28, and both are recorded on #76 as
constraints on N3.** Every account-leak test drove a *refusal*, and the refusal
path correctly discards the fields that leak, so the suite was structurally blind
to the accepting path where four separate leaks lived. And what state can exist
when each `await` resumes was untested — the two worst defects were both
"something buffered, latched or aborted between two steps".

**What this slice does NOT do.** It does not establish WRITE, a store, egress, or
qualified ingress; the provider publishes itself unavailable by default and
nothing at runtime can clear it. It does not prove the pinned binary can run a
turn: the native lane is credential-free, so its only positive result is that the
binary **refuses**, and no test in this repository drives a turn against the real
binary. It does not defend against a vendor that misreports its own mode — the
gate detects an honestly-reported change and cannot detect a lie, because the
vendor authors the reply's content and not merely its timing, which is why
request ids were deliberately *not* randomized. And `raw_reply` carries a
legitimate turn record's payload verbatim; filtering vendor payload would need a
schema this repository does not hold, so a test asserts the operator string **is**
present, deliberately.

**Reports that were wrong.** A review classified the launcher recipe-drift check
as unreachable dead code, on the grounds that the launcher and identity are both
frozen dataclasses; `LinuxLauncher.revision` is a *property* that re-hashes its
own sources at call time, so the check is live and the deletion would have removed
a real guard. A separate review reported the rev 3 plan header as a stale status
conflicting with ADR 0021; the wording is deliberately preserved pre-decision
text, `docs/plans/README.md:63` says so, and the edit was reverted unmerged as
PR #86. Verify a review's premise against source before acting on it.

**Measured, not inferred.** The pinned app-server emits **two notifications
before the gate refuses** — observed in the containment lane, not reasoned about.
They are instrumented but not yet identified: the native lane records withheld
method names, bounded and classified, so a later run will name them. That
observation is also what retired an assumption — the adapter had briefly refused
a `turn/completed` read before its turn was named, which bet on the server never
emitting a turn's notifications ahead of its response. A server that emits
notifications before any turn exists is not one to bet on, so the record is now
buffered and judged once the reply names the turn.

---

## The M8-D2 private Linux host

**Provisioned 2026-09-20. Issue #73. Not qualified, and that is a decision
awaiting the owner, not an unfinished task.**

`constructicon-m8` is a Hyper-V VM: Ubuntu 24.04.5, kernel 6.8.0-139, key-only
SSH, bubblewrap `0.9.0-1ubuntu0.3` held with its digest verified, AppArmor
enabled with `apparmor_restrict_unprivileged_userns=1`. Installed unattended from
a cloud-init seed, so it is reproducible from a config file rather than from
someone's memory of which installer boxes they ticked. Powered off by design —
start/stop, no daemon — and its address is DHCP, so nothing should hardcode it.

**The finding: the qualification path cannot run on a credential host.** The
containment workflow checks out `pull_request.head.sha` and executes it as root,
installing that checkout's AppArmor policy. Any PR would therefore run as root on
the machine holding the subscription credential. No authorization mechanism
repairs that, because the untrusted input *is* the code being executed. The
recommendation on #73 is three roles across two hosts, with the credential host
supplied reviewed, pinned artifacts rather than a checkout.

**A proposal that was withdrawn.** A root-owned authorization marker was proposed
to replace the `RUNNER_ENVIRONMENT == "github-hosted"` gate, and withdrawn: a
marker outlives the property it asserts, survives a rollback or a copied disk,
and can be minted by the very root provisioning it gates. The gate is weak — the
workflow supplies the value to the root builder one line before the check reads
it — but it guards a path now decided never to reach this host, and hardening a
road you have chosen not to travel invites someone to drive down it.

**Drift is visible rather than frozen.** Security updates stay enabled, because
freezing the kernel to protect a qualification record would be image-pinning by
another name, which ADR 0019 rejected. `/usr/local/bin/m8-host-drift` records the
nine facts a qualification rests on and exits nonzero when they move. It
currently exits 2, NO BASELINE, deliberately: it refuses to record a baseline for
a host that was never qualified, because that would manufacture evidence of a
qualification that never ran.

---

## N1 — strict operator-mode contracts

**Merged `57ebcba` (PR #81), issue #74 closed.**

ADR 0021's six strict v3 records, the v1/v3 boundary decoders, one pure grant
predicate, and `SystemDescription` schema 4. Dispatch is on the raw
`schema_version` outside the v1 source-law closure: absent selects the
unversioned profile, exact 3 the native record, every other value refuses, and a
failed v3 parse never falls through to permissive parsing.

**What it does NOT do.** No native process, provider connection, credential,
deployment or live profile exists. Constructing a launch identity is not an
availability proof, and the source says so.

**Preserved deliberately:** the v1 legacy and complete profile bytes, the v1
launch-identity bytes, and `EXECUTOR_LAW_REVISION`, all reproduced from goldens
captured at `d2b8f94` in a detached worktree — because a golden captured by the
same code it validates proves nothing.
