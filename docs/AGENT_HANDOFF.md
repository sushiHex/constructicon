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

## N4 — credential-free startup lane and its host prerequisites

**Merged on 2026-09-24 UTC, each with every check green on its final head:**
- `e26f438` (PR #105), the launch set installed from reviewed artifacts;
- `908b9ae` (PR #106), the narrow `CODEX_HOME` layout;
- `88c033d` (PR #107), the hash-pinned controller environment;
- `40b663e` (PR #108), the authenticated-startup lane.

Everything N4 needs before the owner is now on `main`. The lane holds custody
by the lock it inherits from root's maintenance helper. It passes only on
affirmative facts, reads spend back before any thread, and writes closed
evidence. On #108's final head, every Linux proof passed and all four proof
lanes killed 671 mutants by assertion, none NOT PROVEN.

**Corrections worth carrying.**
- **The unsolicited `CONNECT chatgpt.com:443` was plugin sync.** It is
  disabled in the sealed configuration (`[features] plugins = false`), and
  the relay still denies it.
- **A default literal is a decision made silently.** The lane's `--expected`
  defaulted to `pro`, so an account reporting the other approved plan,
  `prolite`, would have stopped qualification. Qualification now binds the
  approved pair, and active custody requires the recorded literal.
- **A verdict inferred from no faults is not a pass.** A startup whose
  launcher never conversed wrote `faults: []`. Every required fact is now
  named, and a missing one is a fault.
- **Login under active custody would have rewritten the live credential with
  no withdrawal.** Login now refuses outside maintenance.

**Token refresh** ([research](../research/m8-codex-token-refresh.md)). One
device login persists; the pinned client renews it in place when it is used,
never while idle. The server's lifetime is undocumented and stays unknown:
S10 observes whether one refresh succeeds a day after login, not how long a
binding lasts.
A vendor process killed mid-save can empty `auth.json` and cost the binding.

**What this slice does NOT establish.**
- No login, readback, refresh or model request has happened on the host.
- `vendor_conformance_qualified` stays false until the owner-attended session
  records runbook S0 to S10 on #77.
- The two credential managers inside one app-server refresh without a lock
  between them.

---

## N3c — operator-store maintenance and the rest of the N3 matrix

**Merged `a8a8f63` (PR #101) on 2026-09-24 UTC from head `3810b10`. It
completes #76.** The operator store now has these pieces:
- a withdrawn state of `active.json` that carries a generation floor;
- offline withdrawal, activation and reboot re-anchoring, all under the
  retained lock;
- publication under the lock.

An overages-forbidden profile is forced unavailable, whatever its labels say.
The crash matrix, refresh, alias, persistence and non-widening proofs all run
on Linux, with 291 mutants killed by assertion.

**Corrections worth carrying.**

- **A boot-bound anchor made every reboot a dead end.** N3a's immutable anchor
  recorded `boot_id`, so after a restart no helper could recover the binding.
  Maintenance now re-anchors under the lock, but only when the bundle's stable
  identity is unchanged: handle, device, inode, mode, uid and `nlink`, with the
  boot actually changed. The lock is checked on those same stable fields across
  boots.
- **A slice written on a review head must be re-proved on `main`.** N3c's first
  Linux failure came from the merged N3b's routable-address rule, which did not
  exist on the head N3c was written against.
- **A killing test that runs past the harness limit is not a kill.** The
  inventory reports NOT PROVEN on timeout. The fix was to make the test cheaper,
  never to raise the limit.
- **Never put a closing verb next to an issue number in a PR body.** "does not
  close #76" closed #76, twice.

**What this slice does NOT establish.**
- The qualification record's content is operator-supplied.
- Process death inside the re-anchor is unproved.
- Real vendor refresh and overage behaviour are N4 and N5 work.

---

## N4 preparation — in-zone proxy bridge

**Merged `d5c0760` (PR #103) on 2026-09-24 UTC from head `fd6bd8b`.** The pinned
Codex client can use a proxy only as `http://host:port`; no transport accepts a
Unix-socket proxy. So the launcher now prefixes the vendor with a trusted
forwarder whenever it mounts the egress leaf: `127.0.0.1:18080` → leaf → relay.

**Measured, not inferred.** The pinned `codex app-server` exported through
`HTTPS_PROXY` to a controlled peer with no login.

**Corrections worth carrying.**
- **The pinned client connects to `chatgpt.com:443` unsolicited at startup,
  before any login, and the relay denied it.** N4 must trace that code path.
- **An absent evidence fact is not a failed one.** A test first reported "ssl
  cannot import" when the client had simply never reported `ssl`.

**What this slice does NOT establish.**
- The websocket family is proved by source only.
- The host installer does not yet carry the runtime.
- Containment is the relay's claim alone, never the client's compliance with
  the proxy.

---

## N3b — acquisition-scoped vendor-session egress

**Merged `6dac9f2` (PR #97) on 2026-09-23 UTC from reviewed head `9a94959`.**
Issue #76 stays open for N3c.

**What changed.** The native zone now has a way out. Its route-less namespace
gets one read-only socket leaf, `/vendor-egress.sock`, which leads to a
host-side CONNECT relay. Worker launches cannot receive it.

The relay enforces these rules:

- it dials only sealed, pinned, globally routable addresses, and never
  resolves a name;
- the first ClientHello must carry an SNI equal to the CONNECT host, and ECH is
  refused;
- control, stop and deadline are rechecked after every resumed read, before
  anything is forwarded;
- every upstream socket gets zero linger when it is created, so nothing it
  queued survives a controller `SIGKILL`.

**Measured, not inferred.** On Linux, all 9 containment proofs passed and
60/60 mutants were killed by assertion. The evidence and its limits are in the
implementation record.

**Corrections worth carrying.**

- **Inode reuse is real.** A path's `(dev, ino)` is only an identity while
  something holds the inode. Releasing the socket path after closing the
  listener let a replacement socket reuse the number and be unlinked as the
  relay's own. Release the path first.
- **`/proc/<pid>/fd` becomes unreadable once a process's memory is freed.**
  That happens before the process is reaped. A descriptor scan therefore read
  "could not see" as "no holder". Observe a lock by trying to take it.
- **A 0444 socket leaf refuses `connect` with `EACCES`, not `ECONNREFUSED`.**
  Linux checks write permission before the socket type.
- **A pinned address is not automatically resolver-free.** An IPv6 literal with
  a zone id (`%eth0`) goes through `getaddrinfo`. Non-global addresses would
  have reached host-local services.

**What this slice does NOT establish.**

- real vendor destinations, CDN rotation, or the pinned client's
  `HTTPS_PROXY` path (all N4);
- any claim that startup and model traffic are separated;
- the store, maintenance, overage and crash matrix (N3c).

The provider remains unavailable by default.

---

## M8-D2 — reviewed-artifact installation for the private host

**Merged `8c1b14e` (PR #99) on 2026-09-23 UTC. It closes #94; #73 stays open.**

**Root on the credential host executes no repository code.** Stock git, run as
the operator, proves that commit C is on main. An unprivileged judge proves
custody and absence. Every root write comes after that proof, as a fixed
sequence of stock commands. One root command precedes the judge: a read-only
`cat` of the kernel's profile list, whose output the judge needs. The judge
proves that tool's custody only afterwards, and the design document states this
exception (runbook R2/R4). An unprivileged verifier checks the installed state
against git.

**Corrections worth carrying.**

- **`--no-replace-objects` does not disable `info/grafts`.** Also set
  `GIT_GRAFT_FILE=/nonexistent`.
- **Custody applies to the binaries root runs, not only to what is staged.**
  A hashed file that is reopened by path is a new file.
- **Root must not run repository code, including a reviewed installer.** The
  first design ran the reviewed installer as root. The owner's decision reads
  "never running repository code" at the root boundary, and the unprivileged
  judge/verify split is also smaller.

**What this slice does NOT establish.** The real install, the AppArmor load
and the probe on the host run only in a separately authorized operator session
(runbook R0-R7). The runtime and launch closure is N4's prerequisite.

---

## N4-N6 preparation — Claude Code screen and spend bounds

**Merged `5aad791` (PR #98) on 2026-09-23 UTC.** It adds two credential-free
documents: the Claude Code 2.1.267 interface screen and the subscription
spend-bound research.

**Findings that change later decisions.**

- **~~Claude is blocked on every plan by `EndConversation`.~~ Superseded by
  #102:** under the fixed headless launch, the tool's `isEnabled()` gate keeps
  it out of the active tool pool. The gate needs a vendor flag, which stays
  false while nonessential traffic is off, plus the `cli` entrypoint, and `-p`
  forces `sdk-cli`. R9 is **conditionally resolved**; N6 must prove the six
  conditions listed in the screen's "EndConversation reachability" section, not
  an ADR amendment. Deny-style mechanisms (`--disallowedTools`,
  `permissions.deny`, hooks, `canUseTool`) do not work on this tool. Only Pro
  and Max are candidates for R8. Team and Enterprise fail it because
  server-managed settings can inject hooks.
- **Codex on ChatGPT Plus or Pro cannot qualify `forbidden` overage.** No
  vendor setting forbids it; only automatic reload has a cap.
- **An observed zero balance never proves `forbidden`.** Vendor controls are
  candidates that still need N5 refusal proof.
- **The pinned Codex `Turn` has no rate-limit field.** Overage evidence must
  come from `account/rateLimits/read`.

The owner decisions were drafted on #77 and #78 and then made on 2026-09-23. N4
is authorized in advance on #77, with Codex on the owner's ChatGPT Pro 20x.
Under Pro, N5 needs `operator_authorized` overage with bounds the owner has not
yet given (#78).

**Corrections worth carrying.** Business in-flight overshoot is unverified,
not documented. Only the Enterprise source documents it, and the absence of a
Business statement is not evidence either way.

---

## N2 WRITE — owned callbacks, capture and restart evidence

**Merged `184ff4d` (PR #95) on 2026-09-21 UTC, base `c38f53d`.** The merged
tree is byte-identical to reviewed head `7b89dcc`.

One fixed `contained_python` callback now composes the Codex task adapter with
the existing contained workspace, capture and gate components. WRITE explicitly
opts into callback registration; READ's request bytes remain unchanged. One
deadline bounds the native exchange and sequential workers. Request identities,
callback completion and binding observations are affirmative facts, not inferred
from absent errors. Workers join before their workspace guard is released.

**Measured, not inferred.** Final-head verification, qualification and all four
Linux proof lanes passed. Linux executed both capture/gate outcomes, both sides
of the candidate checkpoint, and literal controller death with a stopped worker
supervisor retaining the workspace guard. Recovery reused a checkpoint without
another native exchange, callback or capture; uncheckpointed work used a fresh
acquisition. The connector completed its exact-head review with no findings.

**Corrections worth carrying.** Awaiting a worker alone did not observe native
EOF. The corrected owned read/worker race also had to retain cleanup errors and
cancellation. A later report of lost cleanup evidence was refuted: explicit
close reports its cleanup error while active execution reports cancellation;
requiring both in the same exception group invented a contract. Red gates retain
attestations as evidence, not merge authority. Linux-only tests also exposed a
nonexistent `RunState.cancel_requested` field; the journal owns that query.

**What this slice does NOT establish.** The native peer in the WRITE lifecycle
proofs is scripted. Physical worker custody is not native-supervisor store-lock
custody, a live subscription turn, applied vendor configuration, or deployment
qualification. The provider remains unavailable by default. No credentials,
vendor calls, paid API use, frozen-plan changes or new kernel primitive were
introduced. N3b/N3c and private-host qualification are not inherited from N2.

---

## M8 CI — isolated proof lanes and explicit documentation disposition

**Merged `2677fbb` (PR #92) on 2026-09-21 UTC, base `7e5eb03`.**

The same physical proof inventory now runs across four independently
provisioned runners: foundation, lifecycle, combined and mediation. Tests and
mutants remain serial within each lane, with fresh mutation children and
assertion-only kills. Exact-base policy classifies ordinary prose changes and
aggregates the selected evidence; unknown changes require all physical lanes,
and missing Git evidence refuses. Documentation success explicitly means that
physical proof was not required, not that it ran. Manual dispatch remains full.

**Measured, not inferred.** Final head `68cf1d7` passed CI verification with
2,563 tests and 299 platform skips, qualification, and all four physical lanes.
All 341 mutants were assertion-killed. First job start to aggregate completion
was 8m52s, versus the earlier serial baseline's 24m37s. The first split run on
`c2652af` took 10m40s but summed to 27m58s of successful job durations, about
14% more than the serial baseline because provisioning is repeated. These are
observed durations, not billing estimates or a guaranteed speedup. That first
run's downloaded artifacts retained the baseline's evidence families and
multiplicities; bytes are not claimed identical across hosts. PR #92 carries
the run links and exact-head evidence.

**The correction worth carrying.** Trusting the base classifier was not enough:
the initial aggregate still executed the PR-head gate, which could accept failed
proofs. Both now execute exact-base policy. An introducing base without that
policy permits only the complete successful full-proof shape; an absent base
commit refuses before fallback. Executable workflow-shell tests put a permissive
gate at the head and prove it cannot authorize either path. Workflow definitions
themselves remain reviewed CI policy, not a defended boundary against arbitrary
workflow rewrites. The connector finding was fixed, independently checked and
resolved only after final-head CI passed; the merged tree matches that head.

**What this slice does NOT establish.** No runtime authority, credential,
provider call, deployment or vendor qualification changed. Physical evidence
still belongs to the exact head and observed host; prose-only validation cannot
qualify a native route. Deadlines, pins and proof inventory were not reduced.
Windows skips remain skips. The introducing PR ran full because its base had no
classifier, so its runs do not measure the documentation-only Actions path.

---

## N3a — native operator-store custody and binding generations

**Merged `7535903` (PR #89) on 2026-09-21 UTC, base `153ab8e`. Issue #76 remains
open: N3a is the store/lock/generation slice, not all of N3.**

The slice establishes a dedicated native-only store, a lock retained through
the materialized lifetime, affirmative initial/launch/terminal binding checks,
immutable descriptor publication, and same-path replacement refusal after a
fresh interpreter starts. Linux evidence covers native-only access, lock
handoff and supervisor custody after controller death. The merged tree is
byte-identical to the reviewed head `c12a681`.

**The correction worth carrying.** Checking a resolved acquisition path while
retaining its original alias left later guard and cleanup operations vulnerable
to alias retargeting. Retaining only the resolved path was also insufficient:
a fresh provider could resolve the alias to a second disjoint guard tree while
the old supervisor still held the first. Bound construction now refuses a path
that differs from its canonical resolution and retains that checked locator.
This is not an inode pin; canonical ancestors remain in trusted host custody.

**Measured, not inferred.** Exact-head local verification passed 2,407 tests
with 375 platform skips; Linux CI passed 2,483 with 299 skips. Qualification and
containment passed, with 47 N3a mutants assertion-killed locally and in Linux.
The N2 local inventory killed all 82 mutants. The connector found the alias
defect, then reviewed the corrected full head and reported no major issues.
The finding was resolved only after verification; the default branch now
requires resolved review conversations with no bypass actors.

**What this slice does NOT establish.** N3b acquisition-scoped egress and N3c's
complete maintenance/refresh/crash/non-widening/overage matrix remain separate.
No credential, paid call, live subscription turn or production qualification is
proved. Native store evidence uses a harmless credential-free proof client;
`vendor_conformance_qualified` remains false and default production availability
remains refused. Detailed evidence and limits live in the M8 implementation
record and PR #89, not in a claim that all of issue #76 is complete.

**A tracking assumption that was wrong.** GitHub interpreted a negated closing
phrase in the PR body as an issue-closing keyword and closed #76 on merge.
The wording was corrected and the issue reopened. Use `Refs` for partial work;
do not put a closing keyword next to the issue reference even in a negation.

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

**Provisioned 2026-09-20. Issue #73 owns its status and what remains.**

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
repairs that, because the untrusted input *is* the code being executed. #73
carries the recommendation that followed — three roles across two hosts, with
the credential host supplied reviewed, pinned artifacts rather than a checkout —
and owns the decision on it.

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
