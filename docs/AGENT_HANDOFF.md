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

## #186 — completed preservation is not a fresh target

The first maintenance host session preserved its account capture and all
three D2 records, then stopped on unlisted `cp --no-clobber` warnings despite
successful byte comparisons. It was parked before installation or any vendor
request. A continuation validates the retained capture against freshly checked
historical evidence and the archive against the still-unchanged D2 files; it
does not rerun either write, delete evidence or infer success from existence.
The continuation's accepting tests assert both stdout and stderr. Earlier
copy tests established preservation behavior, not that the operator would see
only declared diagnostics. This adds no generic resume machinery and supplies
no installed qualification or live application result.

---

## #186 — host command composition is not deployment evidence

The additive maintenance procedure pins the merged entry and an immutable
source bundle, reuses the existing replacement and qualification paths, and
permits one application attempt only after positive current evidence. Shell
and substituted PowerShell tests establish command guards, not physical host
qualification or a live result. Frozen runbooks remain unchanged.

Review corrected three composition errors before host execution: maintenance
authority must stay outside the launch root's exact inventory; D2 records must
be preserved before its reused check overwrites them; and a refresh-checker
failure is not an explicit unmeasured verdict. The latter now comes from the
exact positively checked evidence digest. Failure preserves partial state and
parks the VM without selecting a cleanup, restore or retry branch.

---

## #187 — an application attempt is not qualification

The operational maintenance entry uses a separate exact-run authorization and
the existing Graph, ControlPlane, RunHost and exclusive attempt record. It
does not repurpose N5 qualification or clear the provider's unavailable
reasons. Preparation pins a reviewed source bundle; preflight proposes actual
resource pins; run reassembles and checks them before recovery; inspection
reads bounded historical evidence without starting recovery. The worker gains
no installation, push or merge capability.

Credential-free Linux tests exercise the entry with a scripted executor and
real capture, gate and journal. That is not a live provider or installed-host
proof. Changed adapter bytes require fresh installation and qualification;
historical g8 acceptance cannot supply them. No fake-provider mode was added
to the installed entry solely to repeat CI on the credential host.

Two publication assumptions were corrected: nominal identifier types did not
constrain stored identifier text, and a JSON byte bound did not include the
CLI's terminating newline. Both now have accepting and refusing boundary
tests. The installed package also has no repository tests or scripts: source
preparation checks fixed reviewed blob hashes rather than looking for those
files beside its module. Historical inspection is not an authenticity proof.

Application identity must include its authorization law, not just its API
assembly. Review reproduced stale authority surviving a change to the core
law. The explicit revision inventory now includes that contract and both
authorization readers; source-drift and omission tests pin the boundary.

A pre-existing portable test raced a real multi-phase run against a short
polling deadline and could cancel a subprocess thread without joining it.
The concrete tests now await the actual attempt result and worker completion;
the portable launcher joins its child before cancellation escapes. Process
deadlines are unchanged. The credential-free double must preserve cleanup
ownership even where it cannot reproduce Linux isolation.

---

## #185 — a finite autonomous exam has an actual accepting path

An ordinary WRITE/capture/check Graph now returns an immutable one-file
candidate and journal-bound acceptance evidence. Trusted code owns the vector
schema, reference, renderer, whole-tree scope check and eight named mutants;
candidate data supplies no expected values or executable code. The normal
repository consumer is present before any candidate attempt. No production
provider, live qualification, model attempt, installation or merge capability
is added, and the finite exam claims neither novelty nor complete coverage.

Concrete portable integration executes capture packs, the gate program and
journal minting; it does not claim physical containment. Separate native gate
cases establish acceptance, extra-file refusal and insufficient-vector refusal.
Positive case counts caught a Windows fixture reporting a trampoline's exit
instead of its child check's exit. Another accepting-path probe found that
internal ASCII escaping could enlarge a legal 13 KB wire past its 32 KB bound;
minimal canonical re-encoding preserves the allowed domain without duplicating
its validator. Both defects are pinned by permitting-path assertions.

A tree-only check did not establish data-only candidate history: a worker could
commit and remove another file before capture. Generic capture intentionally
preserves that history. Final application acceptance now additionally requires
the candidate's sole parent to be the pinned base; a passing generic tree
evaluation alone is insufficient. The JSON byte limit is not a whole-Git-store
budget, and refused released candidates retain the existing retention policy.

---

## #184 — autonomous maintenance accepts data, not self-reported tests

The merged design replaces arbitrary generated Python plus per-contribution
human coverage review with one bounded JSON input file. Trusted reference
rules, deterministic rendering and eight named mutants define the finite exam.
This establishes a design contract, not implementation, native containment or
live-task evidence. Reference authors inspected the target; no blind-oracle or
complete-coverage claim is made.

The trusted harness and ordinary repository consumer must precede the candidate
attempt. Pinning the old target source is not the same as pinning that later
candidate-tree base: proposing JSON against a tree without its consumer would
produce unused data. Historical N5 entry points and deployment authority remain
unchanged.

---

## #179 — disposal abandons accounting, not physical authority

The ADMIN command seals a bounded exact acquisition set and an ownerless
RUNNING baseline. One transaction records its lost/None transitions, public
receipt and private command relationship. Replay proves that historical receipt
before comparing current state; only positively advanced fences yield the
plan-derived supersession refusal. Schema 9 adds the relationship without
rewriting schema-8 provenance or inventing disposal for old opaque loss.

Disposal does not release a lock, invoke provider cleanup, clear RunHost
deferral or schedule a worker. Real walker tests distinguish a fresh resume,
ordinary restarted-host recovery and a stale queued intent. Portable fake
provider custody remains binding after accounting loss; that test is not a
native containment measurement. Four child-process crash seams exercise actual
restart, including comparison before terminal refusal. Public receipt and
accounting hashes contain no private reason-bearing command/plan hash.

Two absence assumptions were wrong during implementation: a missing plan was
not evidence of an unplanned command while its receipt survived, and a missing
command was not a fresh identity while either its private relationship or
public audit survived. Both point readers now consult the independent evidence.
A permitting-path failure also distinguished point world/era proof from a
complete committed event extent: terminalization temporarily reserves an event
before insertion. No validation-bypass flag was added.

---

## #179 — truthful accounting is a coherent public read

Result schema 2 adds complete capability counts and cut-pinned chunked detail;
the unversioned result decoder remains exact and does not invent zero history.
Run status and accounting share a SQLite snapshot. Old cuts survive closure,
resume and reopen, while failure previews explicitly expose their scan/item
limits. The public payload determines the accounting detail hash.

Batch prefetch reuses the canonical pair projection rather than issuing a
whole-journal identity query per pair. This removes repeated scans, not all
global cost. Existing unmarked legacy events remain opaque under the canonical
historical law; current exact-pair foreign contradictions still refuse. Real
legacy fixtures and an explicitly synthetic admitted shape distinguish those
claims. No administrative disposal, physical cleanup, provider operation or
private-host qualification follows from this read-only slice.

---

## #179 — capability accounting starts with a positive run fact

The ADR 0022 provenance slice introduces schema 8, not a disposal API. Every
run has a sealed accounting era; migration commits its exact acquisition
inventory at a validated event floor, and creation co-commits complete history
from zero. Later activity reconstructs the earlier inventory rather than
rehashing mutable current state. Historical lost transitions and initial lost
legacy acquisitions retain distinct migration-only witnesses. Worker authority
cannot create lost accounting or reactivate a historical lost acquisition.

Actual schema-7 and schema-6 writer fixtures reproduce byte-for-byte. The
eventless legacy erasure fixture is a separate, explicitly synthetic admitted
shape, not a claim about those writers. A review found ordinary active point
paths skipped era validation; the shared projection and acquisition path now
require it, with unchanged-state refusal proofs. A different suspected missing
reverse acquisition check was already present; no duplicate scan was added.

These facts establish accounting provenance only. They do not establish
physical cleanup, resource reuse, public result v2 or a disposal command. No
provider, credential, model or private-host operation is involved.

---

## #143 — simplify evidence only after proving its replacement

The further Fable review of ADR 0022 simplifies terminal rejection: it can
follow a monotone supersession comparison separately, with receipt-first
replay. Its second simplification did not survive the connector review:
sparse migration floors cannot distinguish erased eventless legacy data from
complete empty history. Keep a positively sealed era for every run and bind
the exact migration inventory; only co-committed current creation proves zero.
The owner accepted the decision and staged implementation on 2026-10-13.
This is design evidence, not implemented disposal behavior.

One tempting simplification was false: lack of internal `lost` callers does
not mean no old writer can produce lost data. Credential-free probes used the
schema-7 public transition writer and actual schema-6 initial-acquisition
writer, including reopen/migration. Both lawful shapes exist, so both historic
witness families remain. A future implementation must preserve them.

Disposal also does not clear RunHost's failure deferral. The deferring host
requires fresh explicit resume; a restarted host can recover normally. No
accounting transition proves physical cleanup or releases resource fencing.

---

## #175 — initial strict configuration is not a lifetime restriction

The CLI 2.1.296 source audit establishes ordinary tool-pool membership at
execution, but its MCP exceptions need independent closure. Strict MCP mode
excludes inherited configuration at initial loading; the later plugin-refresh
loader does not itself apply that same check. Do not infer lifetime catalog
closure from the first snapshot.

Startup also precedes its reported mode: unknown subscription state can make
remote policy eligible, and headless consent deferral still applies it for
the current run. Parent managed settings cannot override stronger policy;
safe mode retains managed hooks. A SessionStart-supplied prompt can precede
initialize. This is pinned-source evidence, not a live account observation.

Disposable configuration removes inherited settings, not newly fetched policy.
The proposed `byoc` environment preservation does not freeze policy hooks;
it was not adopted. The remote-settings-path name was another false lead:
its accessor is compiled inert in this release.

No READ driver or new physical proof follows from this audit. The conditional
state design, existing contracts and frozen decisions remain unchanged.

---

## #174 — optional inventory fields are not empty tool sets

The pinned N6c source audit supports repeated initialization as a fresh
current-session mode projection, not an expiry or refresh witness. Cache
invalidation is conditional; the model client uses the same route predicates.
The SDK's cached initial/claimed-session answer is a different operation.

At CLI 2.1.296, the native context-usage producer omits both built-in inventory
arrays that the SDK optionally declares. A permitting fake with empty arrays
would invent evidence. The audit therefore holds READ implementation until
the fixed startup predicate is established; it does not prove the client
incapable. Point-of-use mechanical restriction remains a candidate alternative.
The headless quota branch is source-excluded, not every startup helper.

The conditional state design was independently reviewed. Two corrections are
worth retaining: spend callback identity before awaiting a worker, and do not
claim separate worker launches share the native launcher's byte counter. They
share the remaining deadline, with per-call and aggregate bounds. N6b remains
an EOF-closing observation, not a persistent task conversation.

This is source/design evidence only: no new READ code, physical proof, vendor
execution, credential, model call, host change or production availability.
Follow-up ownership and acceptance belong to #175 and #40, not this document.

---

## #171 — initialization completion belongs to the owned exchange

N6b joins the existing process conversation to N6a's finite codec. A mode match
alone cannot complete it: stdin close, actual EOF and the same launch's clean
supervisor/payload result are affirmative requirements. Reentry irreversibly
poisons completion across suspended awaits. Failed launches cannot publish
their captured bytes or original exception chains.

The state review preceded implementation. Two design corrections matter:
checking single-use only at entry misses a suspended first invocation, and
`raise ... from None` inside a catch still retains the original context.
Physical tests must inspect joined handles, not infer joins from a return.

This is not Claude native qualification, startup clearance, a provider or a
model attempt. Fixed Python workers prove the process seam; they cannot prove
actual Claude EOF behavior. Codex historical acceptance separately closes
#77/#78/#41 at distinct READ g6 and WRITE g8 revisions. Live expiry and natural
refresh remain unmeasured; no common current profile or M8 completion follows.

---

## #170 — a crash scenario needs a crash witness

Qualification tests now await an event recorded after materialization, rather
than interpreting a short observer timeout as process death. A separate finite
failure watchdog bounds a stalled test but never supplies the crash fact.
Every owned observer/witness task is joined. WRITE awaits its real lifecycle
report without the redundant outer scenario timer; production budgets and
terminal custody assertions are unchanged.

The original four Windows full-run failures passed an unchanged-head focused
rerun, but the missing original detailed trace prevents an exact-cause claim.
Controlled regressions prove the timer assumptions independently. Review caught
an introduced unbounded wait; its correction makes watchdog expiration fail
without inventing a crash or starting successor recovery.

---

## #168 — Claude mode bytes are not startup authority

N6a begins with a pure initialization codec pinned to CLI 2.1.296 / SDK
0.3.296. The source artifacts were inspected without execution; fake tests
exercise the exact selected Pro/Max mode and refusing paths. The codec emits
only finite verdicts and adds no provider, process, credentials or availability.

The newer protocol's pending permission/dialog lists are load-bearing shape
facts, but empty lists do not prove no inherited prompt exists. Correlation
also does not prove arrival freshness. These limits belong to the later
conversation's explicit state law, not an inferred successful startup. Current
tool reachability and physical store/egress qualification remain independent
obligations; old Claude or Codex evidence does not qualify this pin.

---

## #78 — g8 live WRITE passed at its observed boundary

The [separately authorized g8 WRITE](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6138432607)
passed at `59de73b` after fresh qualification and owner review of actual pins
and smoke. Its schema-2 report affirms a succeeded run, validated checkpoint
chain, changed candidate, candidate-bound passed check, three closed/released
obligations and unchanged target. No target installation or second turn occurred.

One admitted callback completed with an observed successful worker. Served
model, backend requests and vendor retries stay unknown; token counts prove
neither hard spending ceilings nor zero cost. Complete checks and the joined
report, not an empty fault list or mixed-head local gate, establish this result.

The transport stop required bounded owner-authorized resume, not overwrite or
refund. Prior spent state is preserved; accepted READ T5/no-T6 remains its own
pinned history, not a new READ run. This result neither publishes a provider
nor auto-enables a profile or closes N5/M8. Claude and Pi require independent
proofs; acceptance and disposition remain on the owning issues.

---

## #78 — g8 procedure preserves history and the actual-pin gate

The additive [g8 procedure](plans/handoffs/M8-N5-g8-session.md) pins controller
`59de73b` separately from its own documentation revision. It composes the
unchanged reviewed installation and session blocks, checks old-controller g7
continuity before reboot, and gives g8 qualification and the additional WRITE
fresh state and authorization names. It does not replay completed archive or
retention-resume steps, reset the spent attempt, or infer qualification from CI.

The generation check concerns both validated maintenance records' historical
floor, not a live post-activation claim. The publication helper independently
enforces the next generation. Every H7 control remains required; H8 is at most
one conditional refresh. Owner review of qualification evidence and the W4
actual-pin/smoke pause remain separate from the additional-turn budget.

A preparation correction is worth retaining: an upload example must itself
enforce the preservation rule. The new transport requires an absent per-step
package directory before upload and verifies hashes before execution; prose
forbidding overwrite is not enough. Fake-shell evidence establishes stopping
and composition only, not host installation, refresh or a live WRITE result.
Current execution evidence and custody belong on #78, not in this handoff.

---

## #78 — bounded WRITE observations, not another attempt

**Merged `59de73b` (PR #164), byte-identical to reviewed `f6972a8`.**
The owner-authorized narrow adapter exception records bounded callback
admissions, successful response writes and finite worker-result observations
in the existing attempt record. Progress is a lower bound; legacy absence
stays unknown. WRITE reports use schema 2; smoke stays at 1. The qualification
writer now refuses a captured candidate equal to the sealed base before its
checkpoint or gate acquisition. Generic Git and gate semantics are unchanged.

Exact-head Linux verification passed 4,965 tests with 409 skips, strict types
and all five import contracts. Runner qualification and all four physical
lanes passed, including the unskipped real no-change capture test. All 61
WRITE mutants were assertion-killed. Local full verification of the baseline
passed 4,621 with 750 platform skips; the later correction had focused local
proofs and exact-head Linux full verification, not a second Windows full run.

**Corrections worth retaining:** a visible final snapshot is not proof that
directory sync returned successfully. Separately, valid bounded observations
can contradict a successful attempt. The connector found that introduced P2;
both report projection and the public passing contract now share the response
completion law. The fix was reproduced, mutation-pinned and independently
reviewed; its thread was resolved before merge. Zero-callback success, legacy
unknowns and truthful incomplete failure observations remain representable.

This does not establish why the prior live turn captured no change, successful
live WRITE, or a new attempt budget. Its dispatched authorization remains
spent. No host action or model call ran. Changed adapter bytes require fresh
installation and qualification; g7 cannot qualify them. Frozen plans and
`codex_protocol.py` remain unchanged. Current decisions belong on #78.

---

## #159 — archive records by custody, not inherited umask

**Merged `aec6a85` (PR #162), byte-identical to reviewed `21211a6`.**
The additive archive successor preserves the frozen procedures and all
historical bytes/modes. It checks canonical operator-owned 0700 directories,
trusted non-writable ancestors, regular/operator-owned/single-link public
records, same-filesystem rename, and the original provenance/refusal facts.
The controller stays `f6cd85a`; this is not a production-code change.

The introduced assumption was that R11's umask carried into LR4's fresh
shell. It did not: the actual retirement record was 0664, and the old fixture
made every record 0600. The new suite executes those producer blocks in
separate shells under six umasks and asserts preservation. All 61 cases and
ten assertion-killed runbook mutations passed; Windows metadata doubles are
not physical proof. Linux CI passed 4,920 tests with 408 skips, qualification,
all four containment lanes and 170 host-artifact mutants. Local verification
passed 4,579 with 749 platform skips. Independent and connector reviews were
clean on the exact head.

This establishes the reviewed archive procedure, not its execution, g7
qualification or WRITE authority. The successor requires fresh exact-revision
authorization and retains boot/custody/drift checks, owner evidence review
and the W4 pause. Current host state and ownership remain on #78, not here.

---

## #159 — qualification authority survives launch replacement

**Merged `f6cd85a` (PR #160), byte-identical to reviewed `58db676`.**
The launch lifecycle now recognizes the exact optional root-owned
`qualification/` directory without reading its contents or adding it to
disposal. Retirement records presence or absence affirmatively, and subsequent
judges preserve the identity they promised. Only completed-install verification
permits authorized later creation after an observed absence; missing evidence
is never absence. Unknown siblings, unsafe custody, mounts and substitution
still refuse.

Exact-head CI passed 4,854 tests with 408 skips, runner qualification and all
four physical lanes. All 170 host-artifact mutants were assertion-killed,
including 14 new guards. Local verification passed 4,513 with 749 platform
skips. Independent review and the final-head connector review found no
actionable defect. Windows skips are not counted as Linux lifecycle proof.

This fixes the pre-existing composition defect exposed by #158's host session.
It does not install the fix, qualify g7, authorize a new acquisition or remove
historical authorizations. The additive resume draft deliberately shipped
unpinned; deployment must name the actual merge and retain its separate gates.

---

## #78 — g7 deployment stopped at a retained-state boundary

**Procedure merged as `6bc3d6a` (PR #158), from reviewed `39de68f`.**
Final-head CI passed 4,761 tests with 408 skips, runner qualification and all
four physical lanes; local verification passed 4,421 with 748 platform skips.
The connector review found no actionable issue. These were preparation proofs,
not a live lifecycle result.

The later authorized host session passed checked g6 continuity, clean reboot,
the exact reboot-anchor refusal, D2 verification/probe, no-drift checks and
R11 provenance. LR4 then refused before root writes: Stage 3 had legitimately
created `qualification/`, which the older replacement inventory did not name.
The store and installed launch/controller were not removed. No maintenance,
refresh or WRITE followed the refusal.

**Correction to the preparation claim:** shell-block composition alone did
not establish compatibility with state created by the preceding READ session.
Replacement acceptance needs that lifecycle fixture. A final shell exit of
zero was not success: the affirmative retirement verdict was false. Evidence
is on [#78](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6114305256).

---

## #156 — bounded WRITE implementation, not live qualification

**Merged `d22bff8` (PR #157), byte-identical to checked `f3e79d5`.**
The existing qualification lifecycle now assembles one fixed WRITE graph,
contained workspace/capture and fixed gate. Bounded evidence requires matched
attempt identity, validated checkpoints, candidate-bound journal attestation,
settled obligations and unchanged target. READ wire shapes and frozen vendor
modules are unchanged. The credential-free smoke uses its own fixture.

Final-head CI passed 4,720 tests with 408 skips, strict types, all five import
contracts, runner qualification and all four physical lanes. All five new
physical WRITE cases passed; all 37 WRITE mutants were assertion-killed.
Actual smoke and logged-out WRITE runbook rehearsals passed. The local gate
on identical production passed 4,380 tests with 748 platform skips.

**Corrections worth retaining:** a child-only umask alone did not establish
private initial Git metadata in the service lane; `git init --shared=0600`
must apply before those writes, not only in the final config. The ambient
reason for the runner/service difference was not established. Acquisition
containers remain canonical service-owned metadata even though their contents
are untrusted payloads. The connector's root-runner test finding was fixed
by explicitly requiring a non-root POSIX identity, never by relaxing custody.

**Not established:** private-host installation, authenticated WRITE, a target
installation or general vendor conformance. Deployment and fresh generation
qualification remain separate from CI evidence. See
[PR #157](https://github.com/sushiHex/constructicon/pull/157).

---

## #142 — declared controls name destination denial

**Merged `100fb75` (PR #145), from reviewed `9de7012`.** A declared control
requires a positive destination-denial count. Other denial kinds independently
produce an unexpected-denial fault; an EOF-only control therefore carries both
the missing-control and unexpected-denial faults. Clean startup still rejects
every denial kind. No frozen runbook or binary behavior was changed.

The owner released the Stage 3 hold before merge. Exact-head verify, runner
qualification and all four physical lanes passed; the connector completed its
review with no findings. Portable accepting/refusing matrices and assertion
mutants retain both halves of the rule. The local Python 3.12 gate passed
4,202 tests with 740 skips on byte-identical implementation code; final-head
documentation checks passed separately. See
[PR #145](https://github.com/sushiHex/constructicon/pull/145).

**Not established:** a new private-host installation or requalification. The
READ session used its previously reviewed controller, not this later change.

---

## #132 — settlement before a terminal run

**Merged `88fc71d` (PR #147), byte-identical to reviewed `449296e`.**
Terminal transitions now refuse active acquisition obligations under the
journal fence. Cleanup attempts remaining siblings, relinquishes failed local
custody and preserves ownership-loss precedence. An unresolved close may leave
an unowned RUNNING run for recovery; a run status alone is not settlement proof.
Historical terminal/active rows are not repaired by this change.

The owner released the Stage 3 hold after the affirmative READ verdict and
explicit no-T6 disposition on [#78](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6101919423).
The exact-head local Python 3.12 gate passed 4,199 tests with 740 platform
skips. CI passed 4,538 with 401 skips, all four physical lanes, and 75 M8 plus
29 native-recovery assertion-killed mutants. The final connector review
completed without new findings. Windows skips are not physical evidence.

**Not established:** a WRITE attempt, qualified WRITE composition, a private
host installation, or automatic repair of retained historical damage. See
[PR #147](https://github.com/sushiHex/constructicon/pull/147).

---

## #78 — g6 procedure and the completed READ

**Procedure merged as `b38c8ae` (PR #155).** The additive g6 runbook names
installed controller `585df33` separately from the reviewed procedure revision
`ce12de3`. It preserves checked account continuity, composes the established
fresh-boot installation route, and requires all active controls even when
natural refresh is measured. Its shell tests establish command composition,
not host qualification.

The later owner-attended session established g6 and measured explicit H8
refresh. Stage 3's one READ completed and passed T5; the owner declared it
finished with no T6. The shared N5 retry remains unused. Vendor retry defaults
are retained within the fixed deadline; occurrence is unknown. Evidence and
the distinct owner disposition are on
[#78](https://github.com/sushiHex/constructicon/issues/78#issuecomment-6101909329).
No answer text, account identity or private seal is part of that public record.

**Not established:** WRITE completion or general vendor conformance. The old
READ authorization is spent and is not a reusable launch recipe. Frozen plans
retain their original pre-decision wording; current disposition lives on #78.

---

## #78 — explicit active-startup refresh

**Merged `585df33` (PR #154) from reviewed `69a8932`.** The merged tree is
byte-identical to that head. The operator can request managed refresh through
the existing active-startup conversation; ordinary startup and task requests
still select false. No token client, credential reader or new protocol loop
was added. Explicit evidence is schema 5; default evidence keeps schema 4.
Requested refresh is not measured refresh: the existing connection, credential
mtime and clean-startup proof still decides the result.

**Measured.** Local verification passed 4,103 tests with 740 platform skips.
All four Linux proof lanes passed. Downloaded foundation artifacts affirm
that all four pinned-client fake-endpoint cases ran and passed: default stayed
unmeasured, explicit success measured, and issuer refusal and failed readback
stayed unmeasured. All 25 changed/new mutants were assertion-killed. The final
connector review completed without findings. Qualification's first CI attempt
timed out downloading Ubuntu package indexes before the probe; the unchanged
head passed on the second attempt.

**Correction worth carrying.** A declared-denial control can accept a relay
denial, so combining it with explicit refresh could falsely report a clean
measurement. The combination now refuses before side effects at both public
boundaries, with assertion-failing pre-fix reproductions. A successful vendor
account response can also follow a reload or failed refresh; it is not enough.

**Not established:** live-account refresh, private-host qualification, READ
or WRITE completion. Source-derived revisions changed, so a separately
authorized controller deployment and new generation are required before use.
The T3 pin review, T5/no-T6 hold and post-READ WRITE decisions remain intact.
See [PR #154](https://github.com/sushiHex/constructicon/pull/154) and the
[additive procedure](plans/handoffs/M8-N5-explicit-refresh.md).

---

## #151 — structural channel fixtures across Python versions

**Merged `33f5671` (PR #152) on 2026-10-10 UTC from reviewed `df8ca98`.**
The merged tree is byte-identical to that reviewed head. The fixtures now
expose every `Channel` member explicitly, without inheriting the concrete
transport or either protocol. Their journal-backed subclass adds only the
exact-journal proof; production code and identity enforcement are unchanged.

**Correction worth carrying.** Python 3.12's static runtime-protocol lookup
cannot see dynamic `__getattr__` forwarding. The old accepting proxy therefore
failed before the intended journal guard. The regression now positively proves
that local, foreign and unproven doubles all satisfy `Channel`, then verifies
local acceptance and exact-journal refusals, including a foreign journal that
compares equal. A missing-proof refusal cannot pass by failing the wrong guard.

**Measured.** All 14 introspection tests passed locally on Python 3.11.15 and
3.12.13. The full local 3.12 gate passed 4,059 tests with 736 platform skips;
CI's full 3.11 gate passed 4,398 with 397 skips. A new narrow CI step explicitly
ran the 14 tests on 3.12.3 in its own environment. Qualification, all four Linux
proof lanes, and the exact-head connector review passed without findings.

**Not established:** compatibility with every later Python release, host or
controller changes, measured refresh, or Stage 3 qualification. See the
[implementation record](plans/handoffs/M8-implementation-record.md) and
[PR #152](https://github.com/sushiHex/constructicon/pull/152).

---

## #149 — affirmative wrong-plan evidence through refusal cleanup

[PR #150](https://github.com/sushiHex/constructicon/pull/150) preserves the
schema-4 evidence shape while distinguishing an exact approved wrong-plan
`account/updated` from a generic notice refusal. A successfully sent request
can remain outstanding after a notice stops the session. Cleanup audits its
reply under the same structural/account checks without resuming the session
or sending another request; pre-send and duplicate protections still apply.

The operator checker requires the account reading's exact plan refusal and
sealed identity, with at most one matching exact-notice fault. Generic,
missing, contradictory and extra evidence does not qualify. All 183 N2
mutants in the first inventory were assertion-killed, but a connector review
still found a contradictory-notice gap when a reading already carried another
fault. Its correction uses one private coherence latch for both reading and
notice orderings; no existing refusal suppresses that check. Follow-up
mutation, focused and independent-review results live
in the [implementation record](plans/handoffs/M8-implementation-record.md).

**Correction worth carrying.** Earlier successful startup notices cannot
prove the notice shape in a different failed run. The fake reproduction
establishes a sufficient interleaving, not the unavailable raw host payload.
The failed H7 result stays failed. The new
[requalification instructions](plans/handoffs/M8-N5-requalification.md)
preserve its directory and carry the checked account seal into fresh g5
qualification at the new merged commit.

**Not established here:** host requalification, measured refresh, Stage 3
READ, or any vendor/model result. The separate Stage 3 authorization and pin
review still apply. Python 3.12's unchanged structural-proxy test failure is
recorded in #151; a Python 3.11 gate is not evidence for 3.12 compatibility.

## #143 — proposed operator disposal of abandoned capability accounting

**Merged `4f0178d1` (PR #146) on 2026-10-09 UTC from final head `a037cbc`.**
The docs-only change adds [Proposed ADR 0022](adr/0022-operator-disposal-records-abandoned-capabilities.md)
and records its evidence. It merged as Proposed, not accepted: only the owner
may accept it, and implementation requires a separate issue
after acceptance and #132's merge.

**What the proposal says.** An ADMIN-only, idempotent command could abandon
accounting for a bounded batch of exact active `(lease_id, acquisition_epoch)`
rows on a RUNNING run with NULL journal ownership. A co-located transaction
would recheck the run/row fence, move only the named rows to `lost` with no
disposition, and record the canonical transitions and a positively sealed
receipt. Existing `runs_resume` supplies the retry path; disposal would not
cancel, resume, or terminalize the run. Receipt-backed `lost` means only that
the cleanup obligation was administratively abandoned. It does not prove
process death, physical cleanup, lock release, candidate disposal, or store
reuse. Historical opaque `lost` facts retain unknown cause.
The proposal also requires a storage migration (7→8 if no intervening change
advances it) and a `result_schema_version=2` result shape. Acceptance would
therefore carry migration and client-compatibility obligations, not just a
new administrative command.

**Corrections worth carrying.**
- The draft's public request/plan hashes created a reason-guessing privacy
  oracle. The connector finding was reproduced with a credential-free
  synthetic candidate check. The final proposal keeps reason-bearing bindings
  private; run-readable audit, accounting, result, and receipt-reference bytes
  (including reference hashes) would derive only from public data. Private replay
  binding remains. This is hash-oracle evidence, not an implemented command or
  an executed public-surface privacy proof.
- `runs_resume` already supports RUNNING with no live owner; a new retry command
  is not proposed. The obstruction described by #132 is stale-lease
  reconciliation before the walker's first control check, not lack of a resume
  route.

**What this slice does NOT establish.**
- Owner acceptance, implementation, or any changed runtime behavior.
- The proposed crash/race, SQLite, migration, result-surface or accepting-path
  privacy proofs; those remain future obligations.
- Physical quiescence, successful cleanup, or permission for host/vendor work.

See the [M8 implementation record](plans/handoffs/M8-implementation-record.md),
under "#143 — proposed operator disposal of unreconcilable capability accounting".

---

## N5 Stage 4 — WRITE qualification planning draft

**Merged `13921e25` (PR #144) on 2026-10-09 UTC from head `7f30d77`.** The
docs-only change adds the [Stage 4 WRITE planning draft](plans/handoffs/M8-N5-stage4-write.md)
and updates the plan index and implementation record. The document remains a
review draft: all seven S4 decisions were open at merge, and the plan authorizes
nothing. Its proposed implementation, proofs, smoke, host session and model
request are future work. CI's docs-only path skipped native proof lanes; that
is not native execution evidence.
At merge, the owner had confirmed Stage 2 and Stage 3 were unrun. The plan
gates implementation on owner-declared Stage 3 completion, the S4 decisions,
and #132's merged cleanup outcome; planning is not permission to bypass them.

**Corrections worth carrying.**
- The initial g4-reuse route was not compatible with the ordered controller
  procedure: LR9 starts with LR1's fresh boot. S4-4 now recommends the existing
  next-generation route. Conditional g4 reuse still requires a separately
  reviewed, owner-approved no-reboot controller/quiescence procedure and
  sealed-fact equality and compatibility proof; the draft supplies none.
- The independent cross-review also found missing WRITE root-grant,
  observation-bound and checkpoint-recovery treatment. Those are now explicit
  proposals, not accepted decisions or implemented behavior.

**What this slice does NOT establish.**
- Approval of any S4 decision or an approved implementation design.
- Any Stage 2 or 3 host execution, WRITE implementation,
  CI/native/host proof, qualification, production availability, or permission
  for host action or a model request.

See the [M8 implementation record](plans/handoffs/M8-implementation-record.md),
under "Issue #141: Stage 4 WRITE planning draft".

---

## M8 plan manifest — guarded staged refresh

**Merged `d3554169` (PR #140) on 2026-10-09 UTC from final head `88f83b4`.**
`scripts/regen_plan_manifest.py` refreshes named staged plan documents from
staged blobs while anchoring unnamed documents to the committed manifest and
checking the complete staged Markdown inventory. It refuses missing or
drifted entries, unnamed additions, deletions, conflict markers and unresolved
manifest index stages before writing; callers must explicitly resolve a
conflict. Real-Git fixtures cover refusal without changing the manifest,
named updates, no-op refresh, and explicit resolution. Five manifest-guard
mutants were added to the existing M8 inventory; the final PR record reports
all 38 M8 mutants assertion-killed on the final head, with the manifest guards
included. The final CI/review evidence and limits are recorded on [PR #140](https://github.com/sushiHex/constructicon/pull/140).

**Corrections worth carrying.**
- The first implementation trusted the working manifest and enumerated only
  its entries, allowing an unnamed staged plan edit with a matching manual digest
  and an unnamed new document to pass. The committed baseline and complete
  staged inventory close those omissions.
- Text conflict markers alone missed a marker-free modify/delete conflict
  whose index remained unmerged. The final guard checks unmerged manifest index
  stages before reading the baseline. Automatic manifest conflict aggregation
  was removed; explicit resolution is required.

**What this slice does NOT establish.**
- Runtime manifest enforcement or a change to Constructicon runtime behavior.
- Permission to edit frozen plans: naming a document for refresh is not approval
  to change it. Deletion/renaming is also outside the helper's supported flow.
- Linux containment or host/vendor proof from the manifest tests or a green
  general gate.

See the [M8 implementation record](plans/handoffs/M8-implementation-record.md),
under "PR #140: committed plan-manifest baselines and complete staged inventory".

---

## #110 — the CI timing flakes, each now an event

**Merged `d6a7576` (#122) on 2026-10-06 and `8a0d87d` (#139) on 2026-10-09 UTC. #110 is closed.** #118 (`624cc37`) fixed the first three flakes. Neither PR changed production code or raised a bound.
- **Stream timeout (#122).** The portable test releases its injected `ETIMEDOUT` only after it has observed the established reply, the peer hello and the upstream read. The accepted/reset counts and the deadline are unchanged.
- **Driver death (#139).** The harness's native runs under `setpriv --pdeathsig KILL`, so the kernel ends it when its driver exits. The 5 s wait is now only a hang guard. This is harness hygiene, not production evidence.
- **WRITE worker entry (#139).** The test races the worker's entry against the end of `execute`, with no margin.
- **Bridge mutant 4 (#139).** The reset waits for the dial to return, so only the wake can end the forwarder.

**Corrections worth carrying.**
- **The five startup `denied:eof` connections came from the plugins-on control, not the clean run.** Job 112020223955 fails at the control's assertion, after the clean run's zero-denial assertions had passed. #122 attributed the five to the clean run, and its exact-pin search for a clean-run caller rested on that misreading. Its bounded phase and read-length diagnostics remain. #124's awaited analytics exporter replaced the racing control, and the control now requires destination denials only.
- **#118 overstated its driver-death fix.** Its 5 s wait was a margin over the vendor's own EOF drain, which only the vendor's 45 s watchdog bounds at `rust-v0.160.1`.
- **#139's own CI found two more timing dependencies.**
  - The active stage's heartbeat check relied on that same drain (run 37863215371). It now waits for every child of the owner, including the worker's subreaping supervisor.
  - N3b mutant 15 read NOT PROVEN once (run 37865423977) because the peer's accept list can lag the dial. Its test now counts the relay's own upstream sockets.
  - On the final head `7120b7e`, every check passed except `docs`, which was skipped.

**What these slices do NOT establish.**
- Vendor conformance at either pin.
- Any narrowing of the control verdict in `codex_lane.run_startup` to destination denials. That is a controller change, and it lands after N5 Stage 3 (job_5067d4ce7dad).
- A green Python 3.13 run for #122. That run hit a Channel proxy test failure that predates the PR.

The details are in the [M8 implementation record](plans/handoffs/M8-implementation-record.md), under "#110, the remaining flakes".

---

## N5 Stage 3 — the READ session rehearsed on the foundation lane

**Merged `1251f81` (PR #138) on 2026-10-09 UTC from head `30308f4`. Every check passed except `docs`, which was skipped.** `tests/test_m8_n5_read_rehearsal.py` runs T2 to T6 of the read-session runbook exactly as written, on CI's provisioned foundation lane. It uses HS's common file with one CI override, which sets OC's `PY` and the fixture's store key. Its step, "Rehearse the Stage 3 READ session without a login", succeeded on the final head. No earlier CI step had launched the real vendor binary on the base runtime.

The inputs are the N3a fixture store under a synthetic g4, whose revisions are a passing S6a record's digest `Q`, and a logged-out `{}` credential. The credential is restored byte for byte afterwards. The test checks every link of the refusal, not just the final "not dispatched":
- the refusal is exactly `account/read`'s error;
- the relay counted zero connections;
- the vendor exited cleanly;
- nothing after the gate was observed.

A second run, with or without its journal, leaves the record byte-identical. T6 runs under new names.

**Corrections worth carrying.**
- **The store never reads `Q`, by design.** This was Fable's design review (job_08bb94033cdd). The descriptor proves which slot was bound, not that authentication succeeded (ADR 0021:160-163). `Q` is bound through the capability revision instead: the authorization pins that revision, and the provider refuses a mismatch. That is why a synthetic g4 can stand in for the host's real one. Recording `Q` in the descriptor would be new durable authority, so it is not part of N5.

**What this slice does NOT establish.**
- Nothing after `account/read` was rehearsed. The spend readback, `thread/start`, the intent, `turn/start` and a real answer run first on the host.
- T0 and T1 are host-only and were not rehearsed.

See [M8-N5-stage3-read.md](plans/handoffs/M8-N5-stage3-read.md) and the [M8 implementation record](plans/handoffs/M8-implementation-record.md).

---

## M8 CI — every mutation inventory runs in CI and names live code

**Merged `f68019c` (PR #137) on 2026-10-09 UTC from head `24af153`. Every check passed except `docs`, which was skipped.**
A mutation inventory only counts as evidence if it runs, and a mutant only counts if its target still exists. Until this PR, both problems showed up at run time or not at all.
- `tests/test_mutation_inventories.py` runs under `uv run verify` and checks three things without running anything. Each `scripts/check_*_mutations.py` must run in exactly one place in CI. Each mutant's target text must occur exactly once, found the way the harness finds it (`_mutations.mutated`). Each killing test must still collect.
- A new `mutations` matrix job in `verify.yml` runs the six inventories that ran nowhere: `check_m8_mutations.py`, `check_m71_mutations.py`, `check_m8_native_operator_mutations.py`, `check_m8_qualification_mutations.py`, `check_fault_coordinate_mutations.py` and `check_registry_store_mutations.py`. That is 115 mutants. All six legs passed on the final head.

**Corrections worth carrying.**
- **Six of the 27 inventories ran nowhere.** Refactors had also left mutants aimed at code that no longer existed: the N4 bridge mutants, the Stage 1 dispatch mutant, and "cleanup retains every enrolled sibling", which #130 orphaned. That last one now targets #130's loop line, and it is killed.
- **The first of two new mutants on the `rest = acquired[index + 1:]` slice survived.** Its test now also checks that the closed acquisition is not relinquished a second time.
- **A comment or a disabled step is not a run.** Only a running command counts. A step switched off with a literal `false` is refused. A matrix entry counts only where a step runs the matrix value.

**What this slice does NOT establish.**
- Three provenance scripts stay out of CI on purpose, because each one proves something against a fixed base commit: `check_m71_fixture_provenance.py`, `check_m8_compatibility.py` and `check_m8_native_operator_compatibility.py`.
- The implementation record has no entry for this slice.

---

## N5 Stage 3 part B — the read stage, its attempt record and its session

**Merged `caa3eda` (PR #136) on 2026-10-08 UTC. Every check passed except `docs`, which was skipped.** Part A (#135) was already merged. This part adds:
- a `qualification-read` authorization that pins the READ grants, an absolute
  attempt-record path and exactly one epoch;
- `attempt_record.py`, which keeps one record per authorization (decision S3-1).
  The record is reserved exclusively at `acquire`, so no later acquisition can
  dispatch, even after a journal reset. Its intent is written before
  `turn/start`, with expiry checked on both sides of that write. Its outcome is
  `not dispatched` only if the write of `turn/start` never began;
- a fixed read graph whose task literal sits inside the node, so the node's
  source digest pins it (S3-3);
- the session runbook `M8-N5-read-session.md`, steps T0 to T6. T5 passes only
  a run that succeeded with a completed record.

**`codex.py` and `codex_protocol.py` are frozen from this merge (decision
S3-4).** Stage 2's evidence records the adapter and protocol revisions, which
are digests of all of each module, so any later edit invalidates g4. The
freeze has no end date: a change waits for an owner decision on #78.

The turn is not journaled as an effect. The record explicitly sets aside ADR
0018:331-332's rejection of "a durable executor ledger", because one record per
authorization is not a ledger.

**Corrections worth carrying.**
- **A clean result salvaged from a failed exchange used to be published as an
  answer, for every handle.** This gap existed before the slice. It is now
  refused.
- **T6 may spend N5's one more attempt, READ and WRITE together.** Using it for
  a Stage 3 retry leaves none for Stage 4.

**What this slice does NOT establish.**
- The tests are portable. They cover the scripted native client, the entry end
  to end and the runbook's own programs. The twenty-four mutants run in the
  lifecycle lane. Nothing ran on the host.
- Evidence is in the
  [M8 implementation record](plans/handoffs/M8-implementation-record.md) and
  [M8-N5-stage3-read.md](plans/handoffs/M8-N5-stage3-read.md).

---

## N5 Stage 2 runbook and Stage 3 part A — the host-session script and the production host assembly

**Merged on 2026-10-08 UTC. On each final head every check passed except `docs`, which was skipped:**
- `8083a70` (#134): the Stage 2 host-session runbook, [`M8-N5-host-session.md`](plans/handoffs/M8-N5-host-session.md).
- `8c3fea4` (#135): `codex_host.py` and the `mint` and `run` host commands, with the owner's decisions S3-1 to S3-4 in [`M8-N5-stage3-read.md`](plans/handoffs/M8-N5-stage3-read.md).

The runbook references OC and LR instead of copying them. It sets up a fresh session directory next to N4's, which it only reads. It publishes and activates g4 and requires g3 to refuse against it. It then runs numbered refresh attempts with no elapsed-time criterion. LR gains LR9, which replaces the controller after login, and an Order section that runs the probe only once the controller is current.

The host assembly builds the operator provider only from installed facts. `sealed_account` is the code twin of the runbook's `check_evidence`. The three conformance revisions are the sealed qualification digest `Q`. Under S3-2, `Q` is a reference, not a claim of conformance. This closes Stage 1's "no production assembly" boundary. Twenty-one mutants each target one check, and the foundation lane proves the assembly as `m8-service`. The details are in the [M8 implementation record](plans/handoffs/M8-implementation-record.md).

**Corrections worth carrying.**
- **Stage 2 had no runnable script.** The audit at `b0d9556` found the #126 to #129 changes already in the runbook. The session structure was what had gone stale. OC's S1 still named the model by the old `gpt-5.5` literal.
- **Fable's review of #134 found gaps in the first draft.** Among them, H3 expected S1 to print nothing, so a good directory would have been abandoned. LR9 began as a custom install with no failure table.
- **Astra (job_95d1f6760f0b) and the connector review found real defects in #135.** They included a subset check where an exact check was needed, a `__main__` entry that registered a different graph, an unbounded read, open nested shapes, permissive booleans and a linked `closure.git`. All are fixed.

**What this does NOT establish.**
- Neither PR ran anything on the host. Stage 2 had not run when they merged.
- The runbook's five default decisions are for the owner to confirm in the authorization.
- The provider stays unavailable. `Q` claims no conformance, and the evidence records `vendor_conformance_qualified: false`.
- Part B, the read stage, is not in these merges.
- The new modules are not in `PROOF_MODULES`. R19's import check covers them as part of the controller tree.

---

## N5 Stage 1 — the qualification acquisition and its two prerequisites

**Merged on 2026-10-08 UTC. On each final head every check passed except `docs`, which was skipped:**
- `cf40859` (#130): a live loser releases its custody.
- `6fd3ce1` (#131): a lost answer after the lease commit closes the recorded row.
- `b0d9556` (#133): the qualification acquisition, credential-free.

One owner-placed authorization lets exactly one fixed run drive the real acquire, record, materialize, close and reconcile of the codex operator provider. The provider stays unavailable and never dispatches. The authorization is a root-owned `0640` file with `max_epoch` 1, and the root-file reader is its only source. Its budget is the fenced epoch, per journal incarnation. This was proved portably and by the Linux twin on the foundation lane, including real process death, with 16 portable and 8 Linux mutants killed. The design, the owner decisions and the crash table are in [M8-N5-stage1-qualification.md](plans/handoffs/M8-N5-stage1-qualification.md).

**Corrections worth carrying.**
- **Closing nothing on ownership loss did not hand over custody.** A loser that stayed alive kept the codex guard and store lock, so its successor's reconciliation waited until the loser's process exited. When RunHost re-claimed the run in the same process, it waited forever. The walker now relinquishes local custody on loss and writes nothing durable ([design](plans/handoffs/M8-N5-live-loser-custody.md)).
- **A recording exception does not mean "not recorded".** A lost answer after the commit left the row `active` on a FAILED run, and startup recovery never revisits a FAILED run. The walker now settles the outcome against the journal.
- **A run id names only an actor and a key.** The dedicated journal was assumed, not enforced. The entry now refuses a journal that holds any other run, or the authorized run id with a different stored graph.

**What this slice does NOT establish.**
- Stage 1 had no production assembly, so the Linux twin was the only composition. #135 added the assembly later.
- A timeout counts as a death, so no relinquishment fires. Expiry and leases read two different clocks. The root grants are unpinned, and the first stage that dispatches must pin them.
- Single consumption across a journal reset is left to the first stage that dispatches.
- A FAILED run whose own cleanup fails can still keep active leases. This was already true before these PRs and is tracked in [#132](https://github.com/sushiHex/constructicon/issues/132).

---

## N5 — `account/read` recovery, the sealed account identity and S6b at rust-v0.160.1

**Merged on 2026-10-07 UTC. On each final head every check passed except `docs`, which was skipped:**
- `347ffee` (#127): `account/read` recovers from a 401 on the real binary, without a real credential. No production code changed.
- `72d2021` (#128): the sealed account identity.
- `5620223` (#129): S6b's shape at rust-v0.160.1, measured on the real binary.

The production startup lane drives the pinned binary with production's configuration, command, URLs and eight-connection bound. The only fakes are the destinations: one HTTPS server at `127.0.0.1:443` serves `chatgpt.com` and `auth.openai.com` by SNI, and the store holds a fixture credential. Each of #127's cases opens with the pin's recovery: two old-bearer 401s, then one refresh. A clean recovery reaches all four methods with `refresh: measured`. A refused refresh leaves `auth.json` byte-identical. An account change is refused before any new-bearer check, and an unsealed backend is refused by `routing_faults`. The account-recovery lane now runs every case sealed. Its `stranger` case, sealed for another login, is refused by the identity fault. Mutants N5-A1 to A9 (A5 dropped) and N5-L4 are killed ([design](plans/handoffs/M8-N5-account-read-recovery.md), [identity](plans/handoffs/M8-N5-account-identity.md), [record](plans/handoffs/M8-implementation-record.md)).

**Corrections worth carrying.**
- **`ExpectedAccount` bound the plan, not the account.** A switch completed before the adapter's reading would have shown another `pro` login as a clean reading. The seal is now `<plan>/<identity>`, where the identity is a digest of `account.email` and `workspaceRouting.chatgptAccountId`. Neither value is kept. `LANE_SCHEMA` is 4.
- **S6b expected `account/read` to pass without `chatgpt.com`.** At rust-v0.160.1, `account/read` checks the workspace there itself. The reading is denied at the relay and the run stops at the third method. Left as it was, the Stage 2 host session would have failed at S6b. A new `unrouted` case measures this on the real binary, and `check_evidence`'s `denial` mode now requires this shape.
- **The still-unauthorized case did not reliably reach the eight-connection bound.** #127's body says it does, but three vendor discovery callers race. A sixth case, `bounded`, proves the refusal deterministically under a three-connection bound.

**What this does NOT establish.**
- Every reading and refresh here went to the fakes. None reached the vendor.
- The production binding. Stage 3's assembly must take the seal from the generation's qualification evidence and check it against its sealed digest.
- A switch that only the vendor's hidden user id would show, or a switch made and undone between the two readings of a run.

---

## N5 Stage 0b — the rules at the pin and the native tool inventory

**Merged on 2026-10-07 UTC. On each final head every check passed except `docs`, which was skipped:**
- `c8769af` (#125): the remaining Stage 0b rules at `rust-v0.160.1` (`d27764b8`).
- `ddd3118` (#126): the native tool inventory, measured and closed. The design is [`M8-N5-native-tool-inventory.md`](plans/handoffs/M8-N5-native-tool-inventory.md).

**What #125 established:**
- Production seals `gpt-6.1-sol` at `model_reasoning_effort = "low"`. One rule, `codex_catalog.catalog_choice`, makes that choice. CI checks the sealed literals against the installed catalog. The provider refuses a grant whose effort differs from the sealed one or names none.
- `EgressRelay.denied` is the only place the relay's counters are read. The provider refuses the turn on any denial, so a successful answer cannot mask one.
- `check_evidence` binds lane evidence to the installed adapter and protocol revisions, the runtime digest, the vendor client and the catalog.
- Any `workspaceRouting` other than absent, or `https://chatgpt.com` with a known residency override, is refused before any turn.
- When a total has no input tokens, or a compaction ran, usage is reported as unknown, never as zero.

**What #126 established.** Under the production recipe, the real binary offered fourteen native tools (CI run 37614544749). In WRITE, `contained_python` could be reached only through `exec`. Three layers close this: a sealed catalog the launcher mounts on each launch, a sealed `environments.toml` with `include_local = false`, and `TOOL_CONTROLS`. On the real binary, sealed READ offers nothing and sealed WRITE offers exactly `contained_python`. All 18 known native names are refused. A real-zone test shows that production's launch path mounts that same seal.

**Corrections worth carrying.**
- **Removing `apply_patch_freeform` did not remove `apply_patch`.** Its handler registers whenever an execution environment exists and the model advertises the tool. Separately, the pinned catalog's tool selectors outrank the configuration.
- **`ADAPTER_REVISION` version 1 hashed only three class bodies.** It now hashes the whole module.
- **`CODEX_CA_CERTIFICATE` widens trust instead of narrowing it.** Trust roots are not a containment control. The egress relay is.
- **`request_max_retries = 0` on the built-in provider would be silently ignored.** Retries stay at the vendor defaults, by owner decision on #78.
- **N4's rule that a denial must not be fatal to the turn is reversed.**
- **`[agents] enabled = false` also blocks the collaboration tools without the catalog layer.** The design had not predicted this.
- **#126 added an evidence field without changing `schema_version`.** `LANE_SCHEMA` is now 3.

**What this does NOT establish.**
- Requests after a remote compaction are not proved, and neither are hidden tools under names not yet known.
- The voice host claim is proved from source only.
- The backend request count is unknown.

The details are in the [M8 implementation record](plans/handoffs/M8-implementation-record.md).

---

## N5 Stage 0b — the protocol at the pinned shapes, and the pin at rust-v0.160.1

**Merged on 2026-10-06 UTC. On each final head every check passed except `docs`, which was skipped:**
- `0e5058e` (#123): the protocol at the pinned shapes, landed at `rust-v0.153.4`. The shapes were read at both 0.153.4 and 0.160.0 and are identical.
- `e8b3e56` (#124): the pin moved to `rust-v0.160.1` through the upgrade routine in [`M8-N5-state-review.md`](plans/handoffs/M8-N5-state-review.md).

**What #123 established.**
- `account/updated` passes only as exactly `{"authMode": "chatgpt", "planType": <an accepted plan>}`. Every notice and the first `account/read` must name the same plan. A contradiction latches as a fault.
- The answer is the single `agentMessage` in this turn's `turn/completed` summary. A READ turn that completes without one is damage. Usage is the last `thread/tokenUsage/updated` total. The served model is the last `model/rerouted` target, and it is unknown when there is no reroute.
- Partial text is kept as an observation only. The adapter refuses a turn that never completes and publishes none of that text.
- The placement and combined lanes fold the real binary's wire through a drain to EOF. They assert the answer `"fixture complete"`, usage equal to the number of fake responses served, and no damage. Mutants N5-1 to N5-29 and the re-anchored usage bound are all killed.

**What #124 established.**
- The foundation lane checks the package's Sigstore bundle with cosign `v2.6.5`, which is pinned by sha256. The certificate's workflow SHA must equal the catalog commit `d27764b8`. The first run printed `Verified OK`.
- `goals = false` is set in every recipe that turns the other built-ins off, production included (N5-P1). All four real-binary lanes pass at the pin: foundation, lifecycle, mediation and combined.

**Corrections worth carrying.**
- **The old decoder read fields the pinned `Turn` does not have** (`turn.output`, `turn.model`, `turn.usage`). A real turn would have decoded as a success with no output.
- **At 0.160.1 the goal tools reached every request.** They became visible on ephemeral threads, and that caused all 99 mediation and combined failures. The first explanation of the cause was wrong, and cross-review corrected it.
- **The plugins-on startup control never actually ran plugin sync.** It raced unawaited requests against shutdown, and at 0.160.1 it stopped connecting. The control now uses analytics, which has an awaited flush, and it requires `CONNECT ab.chatgpt.com:443` (N5-P2, N5-P3).

**What this does NOT establish.**
- Vendor conformance at either pin. The lane turns were served by fake responses.
- That a `model/rerouted` target is the model that finally served the answer. Publishing it as the served model is a design choice.
- That `account/updated` arrives at startup. A no-login startup sent none, so this is left for the 0.160.1 audit.
- The rest of Stage 0b: `workspaceRouting` under decision 2, the sealed model and effort, relay denials in the provider outcome, the `check_evidence` identities, the `account/read` recovery tests, and the trust-root and voice-host controls. Details are in the [M8 implementation record](plans/handoffs/M8-implementation-record.md).

---

## N4 — the owner-attended session on the private host

**Merged, each with every check green on its final head:**
- `29a5fa5` (#111): `verify-launch` observes the store without listing it.
- `def8e73` (#112): the reviewed operator commands and session runbook.
- `799da8d` (#113): the lane reads the installed `runtime.json`, and `preflight` exists.
- `92b956e` (#114): the zone trusts the CA store that installation admitted.
- `1138564` (#115): the owner's `operator_authorized` overage bound.
- `88effe1` (#116): launch-set replacement that never touches the store.

**On the host** ([#77](https://github.com/sushiHex/constructicon/issues/77)):
- **S3:** the owner's device login succeeded on 2026-10-02.
- **S0 to S9:** all passed at `88effe1` on 2026-10-03, including:
  - the lock control and the denial and wrong-plan refusals;
  - a clean restart with re-anchoring;
  - g3 active.
- **S10:** ran clean on 2026-10-04, about 69 hours after login, but refresh was *unmeasured*. No connection reached `auth.openai.com` and the credential did not change.

**Corrections worth carrying.**
- **The zone had no CA store.** The pinned client's default TLS found no roots, and the device login died before a code appeared.
- **"Proved zero purchased credits" refused a free grant.** The readback cannot tell a grant from a purchase. The owner's bound now leaves spend to the account's own settings and starts no turn while its spend control is reached ([#78](https://github.com/sushiHex/constructicon/issues/78)).
- **Automatic security updates drift the runtime snapshot**, and they stay enabled. The store lived inside the directory the fixed removal deletes, so every update would have cost a login. Now only disposable artifacts are retired (`M8-N4-launch-replacement.md`).
- **Refresh is lazy.** A token valid for 69 hours triggered none, so one day after login was never going to measure it. At the pin, the client refreshes when the access token's own `exp` is within 5 minutes, or after a 401. The 8-day interval is only a fallback for a token with no `exp` ([research](../research/m8-codex-token-refresh.md)). The `exp` is unobserved, so when a run would measure refresh is unknown.
- **A lane removes its own lane directory.** A retry needs a fresh name for its evidence file only.

**What this does NOT establish.**
- Refresh is unmeasured, so `vendor_conformance_qualified` stays false.
- No model request has run. N5 needs its own authorization: model, task data, token budget, READ or WRITE.

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
Under Pro, N5 needs `operator_authorized` overage with bounds. The owner gave
them on 2026-10-01
([#78](https://github.com/sushiHex/constructicon/issues/78#issuecomment-5945414633)):
the account's own settings bound spend, and Constructicon enforces no ceiling.
It starts no turn while the account reports its spend control reached. This
supersedes the zero-purchased-credit bound
(`M8-implementation-record.md`, "The owner's `operator_authorized` bound").

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
