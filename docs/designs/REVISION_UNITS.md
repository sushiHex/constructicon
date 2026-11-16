# Revision units

**Status: the owner selected option 1, the preservation contract, on
2026-11-16 ([decision record](https://github.com/sushiHex/constructicon/issues/438#issuecomment-6914406199));
the other three questions remain open.** Prepared for
[#438](https://github.com/sushiHex/constructicon/issues/438), against
`558dc44d04174f7241ed8a255a63bf602ba8fa4a` on 2026-11-16.
This record proposes a contract; it accepts no boundary and changes no identity.

## Recommendation and owner choice

Adopt **whole modules, explicitly listed at each owning identity function**,
while preserving every existing source input and the existing kernel member-law
hashes. Small modules permit later separation of concerns; declaring a list
alone does not make an identity narrower. Keep current identities intact until
a separately reviewed implementation supplies its exact before/after inventory.
Do not replace module hashing with symbol slicing: Codex adapter v1 missed
module-level rules called by its hashed classes (`substrate/executors/codex.py:2773-2777`).

The owner has three explicit options:

1. **Preservation contract (recommended here).** Keep explicit whole-module
   lists and existing kernel member laws, with reviewed coverage inventories
   and targeted sensitivity checks.
2. **The contract plus Fable's tests-only closure check.** Parse static package
   imports in CI, compare coverage with a reasoned baseline that may only shrink,
   and reject removals of currently hashed inputs. No runtime identity changes
   belong in that first test-only slice. This can expose new import edges, but
   it adds a baseline/deny policy and cannot prove semantic closure: imports may
   overstate influence, and embedded source and runtime artifacts need separate
   treatment. Existing indirect coverage must be traced before classifying gaps.
3. **Keep the current layout.** Make no revision-unit implementation change and
   continue exact impact review under existing identities.

Option 1 trades continued conservative invalidation and manual impact review
for avoiding a new hashing/discovery framework. No option promises fewer
authenticated startups from a list-only change. Narrowing a startup-bound
concern needs its own exact coverage argument and owner decision; no current
covered input may quietly disappear during extraction.

Acceptance of this contract would guide a scoped implementation proposal. It
would not approve an extraction, change a hash domain/version, retire a freeze,
authorize installation or qualification, select a host/store generation, or
authorize a model attempt. This recording wave performs none of those actions.
#438 remains open until the actual owner decision is recorded.

## Authority and evidence limits

[INVARIANTS](../INVARIANTS.md), [ARCHITECTURE](../ARCHITECTURE.md), and accepted
ADRs [0018](../adr/0018-live-executors-are-leased-contained-processes.md),
[0019](../adr/0019-hosted-linux-runners-are-requalified-not-image-pinned.md),
[0021](../adr/0021-subscription-executors-bind-operator-stores.md) and
[0024](../adr/0024-retain-native-executor-metering.md) remain governing.
The [six-unifications draft](../plans/handoffs/architecture-unifications-proposal.md)
is a review draft, not approval of its revision-unit direction or sequence.
Current #438 body and both comments were read; its earlier universal cost
claim is corrected below. The completed Fable advisory was reused, not rerun.
Its manual import table lacked Python execution and issue access; its alleged
uncovered imports are hypotheses, not accepted end-to-end defect findings.

All source `file:line` references below were read at the full revision above;
paths are relative to `src/constructicon/`. The inventory records direct hash
inputs and selected verified indirect pins, not a proven semantic closure of
the package. Source reads and issue/PR inspection are the evidence for this
prose; no new runtime, physical or authenticated qualification was performed.

## Current input inventory

In this table `E/` means `substrate/executors/`, `G/` means `substrate/git/`,
and module names under a prefix have the `.py` suffix. "Whole" preserves the
current source-reading method; it does not equate raw bytes with normalized
`inspect.getsource()` text. Non-source inputs stay pinned too.

| Identity and owning source | Direct source inputs at this revision | Other inputs / role |
| --- | --- | --- |
| Codex adapter, `E/codex.py:2770` | Whole `E/codex` | Startup-bound; full native identity also used by permits. |
| Codex protocol, `E/codex.py:267` | Whole `E/codex_protocol` | Startup-bound decoder/protocol. |
| Claude adapter, `E/claude_provider.py:891-897` | Whole `E/claude_provider`, `claude_read_worker`, `claude_write_worker`, `claude_native`, `attempt_record`; `core/qualification`, `core/permit` | Full native identity; overlap with lane inputs matters separately. |
| Claude protocol, `E/claude_provider.py:879-885` | Whole `E/claude_protocol`, `claude_startup`, `claude_read`, `claude_initialize`, `claude_native_events`, `claude_read_observation` | Full native identity; several modules also bind startup. |
| Claude lane, `E/claude_lane.py:82-120` | Whole `E/claude_lane`, `claude_maintenance_session`, `claude_startup_qualification`, `claude_maintenance_mode`, `claude_startup`, `claude_protocol`, `claude_native_events`, `linux`, `claude_native`, `egress`, `claude_initialize`; `substrate/_lifetime`, `core/identity`; plus `EvidenceFile` and `_fsync_directory` from `E/codex_lane` | Startup source revision, distinct from Claude adapter/protocol. |
| Store laws, `E/operator_store.py:1775-1777` | Whole `E/operator_store`, independently under layout and mount/lock domains | Descriptor/sealed-store checks compare both; not proof of universal startup replay. |
| Egress, `E/egress.py:178-201` | Whole `E/egress`; also `_record_length`, `client_hello_sni`, `_server_name` from that module | Ordered destinations, resolver addresses, connection/configuration bounds; startup inputs. |
| Linux launcher, `E/linux.py:621-643` | Whole `E/linux`; `core/process.ProcessIO`; `substrate/_lifetime.finish_owned` | Runtime, bubblewrap, policy, profile, limits, vendor paths; Claude adds native recipe revision and recipe selection/command/policy. |
| Claude native recipe, `E/claude_native.py:160-166` | Whole `E/claude_native` | Tree path/digest, command, environment, policy, managed MCP and label; feeds launcher. |
| WRITE workspace, `G/capture.py:95-108` | Whole `G/capture`, `acquisition`, `authority`, `contained`, `pack`, `process`; `substrate/_lifetime` | Launcher, target, Git/Python binaries, object format, pack limits. |
| Contained gate, `substrate/gates/contained.py:196-224` | Whole `substrate/gates/contained`; `G/acquisition`, `authority`, `process`; `substrate/_lifetime` | Launcher, checks, target, Git/Python binaries, object format; versions join check-set hash. |
| Maintenance application, `api/_maintenance_identity.py:11-21` | Whole `api/plan_manifest_application`, `maintenance_entry`, `_maintenance_source`, `_maintenance_identity`; `core/maintenance`, `permit`, `refusal`; `E/maintenance`, `qualification`; `substrate/gates/channel_reply` | One-run application pin. Application file also supplies definition adapter revision (`api/plan_manifest_application.py:270-273`). |
| M9 installed source, `api/_m9/proposer.py:52-86` | Every package `*.py`, with inventory/byte bounds and symlink refusal | Whole-package installation identity stays whole; trial marker compares it (`api/_m9/trial.py:46-63`). |

Additional existing pins must survive, rather than disappearing because the
initial #438 table omitted them: Claude READ fixture hashes its own module,
`_CONFIG`, `_git`, and whole `G/authority`, `contained`, `acquisition`
(`api/_claude_read_fixture.py:53-62`). Claude READ definition adds its entry
and fixture revision (`api/claude_qualification.py:265-268`). Claude WRITE
report/definition identities cover the entry, shared capture/assembly and
projection (`api/claude_write_qualification.py:144-151,515-518`); the projection
binds `core/qualification_write` and its own module
(`api/_qualification_write_report.py:72-83`). The shared writer also hashes
its module (`api/_qualification_write_graph.py:245`). M9 fixture binds fixture,
runner, renderer, projection, issuer, fake provider and configured inputs
(`api/_m9/issuer.py:83-99`). Pi binds its provider/read and protocol modules
(`E/pi_provider.py:166-172`); this proposal grants no Pi requalification scope.

### Shared law: covered bodies and remaining questions

`core/executor.py:264-278` automatically combines the identity with the v1 law
over `_names`, `Posture`, `ModelSelection`, `EffectiveGrants`, `IsolationProfile`,
`ExecutorGrantPolicy`, `ExecutorProfile`, `ProviderRouteIdentity`, and
`ExecutorLaunchIdentity`. `core/native_operator.py:264-279` similarly combines
the v3 identity with `_names`, the three grant bodies, the v3 policy/isolation/
profile and egress/store/launch records. These imported grant bodies are
indirectly covered; calling them uncovered merely because an adapter list
omits their module is wrong. Preserve these member lists and frozen v1 bytes;
ADR 0021:331-334 requires baseline v1 goldens before editing its closure and
forbids modifying that closure to implement v3.

`core/permit`, `core/maintenance` and `core/qualification` are not members of
those kernel lists. Codex calls the shared permit predicate (`E/codex.py:2655`)
without directly hashing its module into the adapter. Maintenance explicitly
hashes permit/maintenance, and Claude hashes permit/qualification, as above.
One-run assembly independently checks application, workspace, gate and full
executor revisions (`api/maintenance_entry.py:196-213`). This establishes
several coverage paths, not completeness for every qualification entry.
The remaining cross-entry coverage is **untraced**, not a confirmed bypass.

Likewise, the application reads `substrate/gates/maintenance` outside its direct
list (`api/plan_manifest_application.py:404,422,622`). The prepared plan source
pins that helper (`api/_maintenance_source.py:28-34,194-196,273-276`); the gate's
check program embeds its installed source, and assembly compares exact checks
and requested check-set hash (`api/plan_manifest_application.py:434,541-551`).
Those independent pins refute an assumption of no coverage. Whether all local
result-derivation uses are closed by those pins remains **untraced**. Do not
convert either question into a coverage reduction or claimed security defect.

## Which changes actually force which evidence

**A moved source revision does not universally require authenticated startup.**
Codex's startup producer records adapter, protocol, launcher, runtime,
executable/catalogs, configuration and egress (`E/codex_lane.py:350-365`);
assembly compares installed inputs (`E/codex_host.py:176-177`). Changing one
of those recorded values makes that startup record unusable for that assembly.
Claude compares the lane source revision (`E/claude_host.py:106`) and runtime,
vendor, policy/configuration, launcher and egress (`:160-170`); the lane list
above explains which source edits reach that comparison. Claude adapter and
protocol changes therefore need analysis of overlap, not a blanket rule.

Store-law edits invalidate descriptor comparisons
(`E/operator_store.py:1008-1011`). The CLI accepts a non-unqualified evidence
digest when publishing and checks its equality at activation (`:1611-1629`);
this alone does not prove an old startup can be reused after a law change.
That operational policy is unresolved here. Actual store maintenance still
requires withdrawal, a new non-reused generation and completed qualification
under ADR 0021:186-198. ADR 0019:46-52 separately requires physical proofs on
each supplied CI host; ADR 0024:20-25 binds metering to the exact adapter.

Application, workspace, gate and full executor pins can require fresh one-run
authorization/assembly even when startup-bound values stay equal. Any package
source edit also moves M9's installed-source identity. Source tree, installed
controller, observed boot/host, store generation, qualified evidence digest and
one-run inputs are separate facts: measuring one supplies none of the others.
ADR 0021:395-396 separates source screens, authenticated startup and real model
use, and requires independent provider/posture qualification. This record
authorizes neither a startup session nor a model-turn qualification.

The remaining READ exporter is already [#440](https://github.com/sushiHex/constructicon/issues/440)
/ [PR #441](https://github.com/sushiHex/constructicon/pull/441), a separate
behavioral slice. Editing `G/contained` independently moves WRITE workspace,
Claude READ fixture/derived configuration and M9 source, through the inputs
above; it does not intrinsically move adapter, protocol or contained-gate
source identities. Shared-law edits can add effects. It needs no revision-unit
implementation first. Do not expand that slice into new scripts or a launcher
change to establish an order; reassess exact source overlap when composing work.

## Implementation boundary if the contract is accepted

Keep each source list beside its existing identity function. Before extraction,
record every direct/indirect coverage path being retained, distinguish startup
from other pins, and check source read/embedded programs as well as imports.
Shared law must remain in every relevant dependent pin after a move. Targeted
sensitivity checks should alter a representative module-level rule and shared
helper and positively show every claimed dependent identity moving; preserved
v1/v3 law and serialization goldens remain binding. Such checks sample stated
coverage; they do not prove all semantic influence. Review the inventory with
the exact diff, and separately test any intended behavior change.

Option 2 retains Fable's proposed AST-closure test, baseline ratchet and
dynamic-import deny rule as an owner alternative; option 1 does not recommend
them for this slice. Imports can overstate influence, miss
embedded source/runtime artifacts, and already-covered kernel bodies make a
naive gap table misleading. An exception baseline introduces another
policy. Propose automation only for a concrete demonstrated omission and an
explicit owner choice; do not claim it proves semantic completeness. Runtime
AST discovery, blanket import hashing, symbol slicing and a source registry
are not part of any option here.

The frozen S3-4 decision says Stage 3 merges before Stage 2 because later Codex
adapter edits invalidate g4 ([record](../plans/handoffs/M8-N5-stage3-read.md),
lines 37-39). Its durable [handoff](../AGENT_HANDOFF.md) at the baseline, lines
3471-3474, freezes both `codex.py` and `codex_protocol.py` without an end date,
pending an owner decision on #78. N6 explicitly requires an applicable owner
exception and inclusion of a cross-provider helper in both source identities
([record](../plans/handoffs/M8-N6-WRITE-state-review.md), lines 55-61).
Acceptance of this document would not supply either exception. F2 lifecycle
unification, F4 neutral helpers and an optional launcher split remain separate
implementation choices with exact overlap, behavior and requalification scope
to review. No extraction or stricter-settlement adoption is bundled into the
contract decision, and no frozen artifact is edited by this proposal.

The S3-4 exception, whether store-law source changes require fresh authenticated
startup, and whether a launcher split joins a later requalification or waits
remain explicit open owner decisions. Selecting a coverage option settles none
of them.
