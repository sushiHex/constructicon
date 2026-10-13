# M8 N6 — fixed-startup restriction audit

Source investigation for [#175](https://github.com/sushiHex/constructicon/issues/175),
under [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md).
This advances the [N6c READ state review](M8-N6c-READ-state-review.md); it does
not authorize a permitting READ implementation or qualify a native launch.

## Pin and method

The pin remains CLI 2.1.296 / SDK 0.3.296. Artifact provenance and all three
member digests are in the [N6a review](M8-N6a-state-review.md).
The Linux member was rehashed on 2026-10-13 as
`24972e3bc859fab2b46ed4c1e51f7d6130f06d3bd550811a114640de3370d0de`.
`B@` identifies a zero-based byte offset in that member's embedded source.
Two focused source reviews examined environment/startup and tool membership;
the orchestrator independently read the decisive branches. Nothing from the
vendor package was executed or imported. No credentials or private host were
used. Source reachability is not a measured operator-account event.

## Positive progress: membership at use, not missing inventory

The native context-usage response still omits the two built-in inventory
arrays. They must not become empty arrays in a permitting fixture. However,
ordinary tool dispatch looks up the operation in the current permitted pool
(`B@217867211`); a missing operation returns a refusal (`B@217868572`). The
complete built-in inventory supplies an explanation, not fallback execution.

Explicit empty `--tools` freezes an empty launch-kept set through `t2r`
(`B@223700256`). Ordinary built-in pools pass `i5` / `dAt`
(`B@215149653`, `B@215150088`). Plugin `$.tool.register` refuses the resulting
`builtInToolsDisabled` state (`B@217913316`). This is useful point-of-use
restriction evidence, not proof of a complete fixed catalog.

The launch-list predicate expressly exempts MCP tools, host-only native tools
and EndConversation. Consequently a candidate recipe additionally needs:

- EndConversation mechanically disabled, including its feature/cache inputs;
- no attached-machine path (the inspected host-only marker consumer constructs
  remote-machine PowerShell at `B@233026047`);
- one exact host-owned SDK MCP server/catalog, with all later additions closed;
- no CLI or initialize structured-output schema. Print assembly appends that
  tool after the normal filter (`B@233621950`); the selector reads the host
  launch option (`B@207239350`), set by initialize when supplied
  (`B@233771171`).

Strict MCP configuration supplies a narrower positive fact: initial loading
selects an empty inherited server map without calling the inherited-config
loader (`B@225521062`). Initialize registers the host's explicit SDK server
names (`B@233678762`). Authentic MCP summary rows include name, server name,
token estimate and loaded state (`B@217704983`); they can corroborate that
server without inventing built-in rows.

**Initial strictness is not yet a through-turn proof.** The print path's
`ed` / `applyPluginMcpDiff` (`B@233642519`) calls `SL` with `admits: jie()` and
merges discovered servers with SDK entries. It does not itself test strict
configuration. `jie` supplies its filter only in bare mode (`B@228679904`).
A complete recipe must either exclude every relevant refresh trigger/source
or establish a fixed restriction on this path too. Merely observing the
correct initial MCP rows cannot supply that obligation. This is a source
proof gap in the candidate recipe, not a reproduced live strict-mode defect.

## Environment controls and the simpler physical candidate

Empty setting sources do not exclude global `ce().env` or policy/flag settings.
Both environment applicators use them (`B@211250757`, `B@211252043`), and
settings changes can reapply environment (`B@224481527`). Initial spawn values
alone are therefore insufficient.

An explicit `CLAUDE_CODE_ENVIRONMENT_KIND=byoc` selects host-orchestrated
environment handling (`B@211228786`). The first safe applicator snapshots
initial key names (`B@211250474`); `filterSettingsEnv` routes settings through
the filter dropping those keys (`B@211245801`, `B@211237006`). This can protect
explicit nonessential-traffic and GrowthBook suppression values. It does not
protect omitted keys, freeze non-environment policy, or close direct host
credential injection. Nor is it proof that adopting all `byoc` semantics is
appropriate. No such marker is added to Constructicon.

Prefer a physically narrow credential projection with disposable other state
if independently qualified. That removes inherited global settings without
pretending the process is another vendor host. It is not implemented by the
current Codex-specific mount recipe, and Claude's refresh/lock/temp-file behavior
still needs its own layout proof. No file is copied or parsed to create one.
At this pin the credential path is `.credentials.json` (`B@209495828`);
the writer's rename fallback includes `EBUSY` (`B@207932847`). That supports
investigating a single-file bind, not claiming refresh has passed physically.

## Concrete startup obstacle: managed policy precedes the mode gate

The proposed ordinary local headless recipe does not establish unconditional
exclusion of remote managed authority before its first mode observation:

1. Remote-policy eligibility `KA` / `k` (`B@211226001`) includes an OAuth
   subscription whose type is unknown/null through `Y`. Known Pro/Max can be
   ineligible under additional provider/profile/API-key conditions, but the
   adapter cannot infer those internal facts from an opaque store binding or
   a later initialize reply.
2. `pt` (`B@224524999`) returns before loading only when eligibility is false.
   An eligible path can load remote policy. Disposable local state alone does
   not exclude this new input.
3. Headless consent is not a blanket refusal. `ye` selects
   `deferred_non_interactive` (`B@224506583`); `Se` accepts it
   (`B@224508469`). The loader publishes a verified current-run payload with
   deferred consent (`B@224531478`) and applies it for that run
   (`B@224532044`). Deferral concerns persistence of consent, not withholding
   all policy. The verified payload is served by `$b` / `gl`
   (`B@209059296`, `B@209059015`).
4. `--managed-settings {}` does not replace higher policy. The parent tier is
   conditional and restrictive-filtered (`B@209121419`, `B@209132714`).
   An empty parent object cannot establish an immutable policy ceiling.
5. Safe mode does not make the SessionStart dispatcher return early: its
   feature table retains hooks, and `br` returns early for safe mode only
   when that feature is absent (`B@213479626`, `B@213481141`). Managed hooks
   remain relevant. Bare mode does exclude this hook path, but loses the
   subscription authentication required by this work.
6. SessionStart can record `pendingInitialUserMessage` (`B@218081521`). Fresh
   `sH` awaits the startup hook work (`B@233791456`); print awaits `sH`
   (`B@233574724`), then consumes and prepends that message (`B@233575885`).
   The first initialize branch follows (`B@233677421`), with its mode
   projection at `B@233772528`. An idle
   reply or empty pending permission arrays cannot prove the absence of this
   earlier work. Hook selection and execution need their own source closure.

This establishes why the proposed controls are insufficient, not that any
actual account supplied such policy or that every possible client integration
is impossible. Even a later mode refusal cannot undo a startup helper already
run. ADR 0021 requires exclusion or qualified bounded authority at that point.

Two tempting workarounds were rejected on source evidence. The release's
`Kk` (`B@209049690`) returns no value, so the remote-settings-path environment
name does not supply the proposed override here. The policy exclusions for
remote hermetic / local-agent / coworker markers describe other host modes;
claiming those markers solely to bypass eligibility is not a reviewed ordinary
headless recipe. No alternate authentication route or relaxed ADR is adopted.

## Disposition

The conditional READ implementation gate remains closed. The concrete missing
contract is a fixed startup policy/helper boundary and a through-turn exact
MCP boundary, not another executor or process abstraction. A future supported
control or qualified physical restriction must cover both before the proposed
one-READ driver gains an accepting path. A successful initial catalog snapshot
or a test-only `startup_ok` would hide the problem, not solve it.

No runtime implementation, new test, mutant or physical proof is claimed by
this audit. Existing repository gates validate the documentation change and
baseline; they do not prove native behavior. Status and further ownership stay
on #175 and #40. Frozen plans, accepted ADRs and Codex code remain unchanged.
