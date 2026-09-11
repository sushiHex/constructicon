# M8 combined startup and mediation evidence

Status: partial combined investigation; no production qualification.
Exact-head readiness and final artifact links belong to
[merged PR #58](https://github.com/sushiHex/constructicon/pull/58).
Owner-authorized investigation: [issue #57](https://github.com/sushiHex/constructicon/issues/57).
Branch: `investigate/m8-combined-startup`.
Base: `6a5c2e43cfa1bda7f281a66886946668f471c5c7` (merged placement PR #56).

## Authority and bounds

This is the combined slice of the accepted
[provider fixture proposal](M8-provider-fixture-proposal.md), following its
[placement proof](M8-provider-placement-evidence.md) and the
[native qualification plan](M8-native-qualification-plan.md). It does not amend
those frozen documents. Existing startup observations remain in the
[startup evidence](M8-controlled-startup-evidence.md).

Reuse the exact test-only placement launcher, one bounded fake peer, byte bridge,
duplex conversation, acquisition guard, and existing process supervisor. Keep
the binary, model/catalog, runtime base, and bubblewrap pins. No new production
interface, supervisor, broker, ledger, schema, credential, live provider route,
authentication decision, host-policy relaxation, or durable native recovery.

## Acceptance checklist

These are future gates, not executed results. Both pinned profiles (`gpt-5.5`
and `gpt-5.6-sol`) must be observed inside the placement fixture.

1. Inventory each startup origin and its supported control. For managed/system,
   user/profile, project/trust, hooks, skills, plugins, MCP/apps, packaged assets,
   environment, and cloud/account state, distinguish physical absence, a positive
   discovery/execution control, a refusal, and an unqualified surface. A default
   empty listing is not proof that the corresponding source is disabled.
2. Define the provider-request assertion before interpreting native observations.
   Controller-authored turns have exact controlled content and sequence. Native
   context is a different field of evidence, with its expected shape and allowed
   variation stated explicitly. Do not learn an arbitrary first request as its
   own reference, authenticate origin by matching text, or silently ignore extra
   conversation turns. Unexpected context is a refused/unqualified observation,
   not permission to widen an allowlist until a positive case passes.
3. Link each allowed native callback to the actual contained worker invocation,
   its output, the returned native tool result, and the completed turn. Bind the
   peer transcript, native RPC/call identities, complete owned `ProcessResult`,
   and post-join peer failures in each record. Preserve both models' distinct
   request/tool wire shapes; `turn/completed` alone is insufficient. Exercise
   patch, image, and model-dependent refusal controls, including positive controls
   that prove a removed tool was reachable before its supported restriction.
   Preserve the worker's existing READ boundary and single physical owner.
4. Exercise a contained descendant/direct-socket request. The endpoint establishes
   invocation membership, not CLI authorship. Preserve this limitation even if a
   descendant can reproduce the exact permitted request; do not call matching
   bytes a process-authentication proof.
5. Test the assertion laws independently with malformed and substituted input,
   including earlier user content followed by the correct final prompt. Kill
   targeted assertion mutants. Preserve placement cleanup/failure controls and
   exact-head local, CI, native, and independent review gates. Audit downloaded
   artifacts, not only test counts, and record failed hypotheses as well as proofs.

## Native-context contract

The placement-only peer checks the final controlled prompt; its historical
acceptance did not validate earlier native context. The combined investigation
must not inherit a stronger claim from that check. Its expected context must be
grounded independently in the pinned release and controlled startup recipe.
Generated identifiers/time fields are observations, not caller authority; any
normalization must name the fields it excludes and why. Tool outputs are bound
to their call identifiers and observed worker results, not accepted as another
free-form user turn.

The fake peer remains a fixed response script chosen by the test controller.
Incoming context never selects executable fixture behavior. A deterministic
request check is a test assertion, not a new provider protocol or authorization
boundary. Unsupported context/state ends the relevant proof as partial/blocked.

## Stop conditions and handoff

A supported-control gap is a legitimate result. If an origin cannot be controlled
without changing the accepted boundary, record its exact reproduction and leave
qualification incomplete. Do not compensate with a second tool-name denylist,
new production restrictions, or borrowed desktop/account credentials.

Native journal/RunHost/home/revocation recovery remains gated on a supported
startup and mediation recipe. Completion here does not accept subscription auth.
Report proved, refuted-by-reproduction, unexecuted, and blocked-by-prerequisite
rows separately to issue #57 and the decision packet in issue #38. An overall
partial result must retain those distinctions. Keep the resulting implementation
PR draft for owner review.

## Executed evidence

The checklist was committed as `e05d362` and strengthened after independent
acceptance review in `35d12db`, before the first test implementation commit.

The first slice adds a full expected conversation assertion to the existing
peer, without changing its fixed response script or placement. Both pinned
models use an explicit controller-supplied `baseInstructions` fixture string;
this is a controlled probe recipe, not qualification of their default prompts.
The source-supported `[skills] include_instructions = false` and
`[skills.bundled] enabled = false` are explicit. Their source is
[`skills_config.rs` at the pinned revision](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/config/src/skills_config.rs).
These controls do not establish that arbitrary startup extensions cannot execute.

The tool declarations in `tests/fixtures/native_combined_tools.json` come from
the already-reviewed native artifact `10281307021`, run `34643786457`, file
`codex-gpt-5.5-contained_python-images-true-unchanged.json`. They are independent
of the new request under test. The assertion preserves the namespaced Sol
framing instead of flattening it, and compares entire declared tool definitions.
Only top-level item IDs are excluded from conversation-content comparison;
they must still be nonempty strings. The only allowed context-text variation is
the UTC date within the controller's 20-second invocation window. Tool call IDs,
arguments, results, message order, permissions text, environment, and controller
prompt remain exact.

The root field inventory and generation settings are also exact. Unknown
`previous_response_id`, `conversation`, and arbitrary context fields refuse.
`client_metadata` and `prompt_cache_key` remain recorded transport annotations,
not authenticated origin evidence; metadata thread/turn IDs must correlate with
the controller's observed RPC IDs. The fixed fake peer neither routes nor selects
behavior from them. The positive patch control additionally permits only a
numeric elapsed-time field between zero and twenty seconds in its otherwise
exact result text. Its actual file content is checked through a trusted read.

The original Sol tool declaration is preserved separately from the restricted
one: `native_combined_sol_tools.json` comes from the same prior artifact's
`codex-gpt-5.6-sol-contained_python-images-false-unchanged.json`. Positive patch
controls select the original pinned catalog; restricted cases keep the existing
restricted catalog. No new catalog transformation or native binary pin is added.
The original catalog is an immutable placement-only asset, checked against its
existing source hash at image construction, not a large bootstrap argument.

The three MCP resource-tool declarations are pinned in
`native_combined_mcp_tools.json` from the same prior artifact's
`codex-project-trusted.json`. Only deliberately enabled MCP positive controls
expect these tools; the empty recipe still rejects them.

`native_combined_context.json` preserves the original Sol agent-role and
delegation context from the prior artifact's
`codex-gpt-5.6-sol-contained_python-images-false-unchanged.json`, and the plugin
usage text from the pinned
[`available_plugins_instructions.rs`](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/core/src/context/available_plugins_instructions.rs).
Neither comes from the request being judged. Only the original Sol catalog
control admits those two agent messages; only the enabled-plugin control admits
the plugin guidance. The plugin-disabled restricted baseline rejects either
addition. Plugin skill names
retain the native `plugin_name:skill_name` form.

Independent source review found and corrected an old owner-death caller missing
the newly explicit model, top-level history fields bypassing the context check,
and worker failure observations attached too late. Worker evidence now includes
the complete decoded result, raw owned process outcome, and existing acquisition
identity before any callback-result assertion can fail.

The first Linux six-case combined baseline passed on `4b8f372` (allowed worker
plus disabled patch/image paths for both profiles). It does not establish the
later strengthened assertion or startup controls. Current portable focused
checks: 148 passed, 28 platform skips; sixteen assertion mutants killed. These
include negative patch side effects, native RPC/peer identity correlation,
untrusted hook attempts, and non-ambient positive-control context. They are
instrument checks, not native qualification.

The origin matrix includes private/account-empty baselines, refused selected
and ignored unselected named profiles, project TOML and inert MCP startup under both
trust states, discovered user/project skills with prompt inclusion disabled, and
JSON/TOML hooks with untrusted, explicitly trusted, and disabled controls. Trusted
hook attempts and MCP execution are deliberate positive controls, not part of the
empty safe recipe. System/managed sources remain physically absent under the
unchanged read-only runtime. No account-authenticated or cloud-managed positive
control is attempted. The local-plugin positive control seeds the pinned
loader's existing cache layout with one inert skill/MCP fixture; it does not
qualify plugin installation, marketplaces, or arbitrary extensions.

### Failed hypotheses retained

The expanded run `34651713774` on `16dc9d5` failed seven cases (76 passed).
Its downloaded artifact is retained as `m8-containment-34651713774-1`:

- Sending the original catalog in setup exceeded the existing 256-KiB line
  bound. The fix moves the same pinned bytes into the immutable test image;
  no transport bound is increased.
- Sol's positive image result omits `detail`, unlike gpt-5.5. The earlier
  reviewed artifact independently confirms that difference; expected results
  now preserve the distinct wire shapes.
- `app-server` rejects `--profile` before RPC. This is a refused configuration,
  not evidence that profile selection works. Unselected profile files remain a
  separate ambient-configuration control.
- A trusted MCP server advertises three native resource tools even when its
  `tools/list` is empty. The pre-existing artifact supplies their exact golden;
  this does not broaden the empty recipe's expected declarations.
- Both trusted command hooks were attempted but failed with `ENOENT`, leaving
  the public marker untouched. The immutable inventory has no `/bin/sh`, the
  pinned hook runner's default shell. Disabled and untrusted controls must show
  no attempt; successful command-hook execution is **blocked**, not proved.
  No shell, runtime-base change, or additional grant is introduced to force it.

The source distinction between hook discovery, trust, and attempted execution
is in the pinned `hooks/src/engine/discovery.rs`, `hooks/src/registry.rs`, and
`hooks/src/engine/command_runner.rs`. A failed hook is not a safe-disable proof:
the fixture must still prove its untrusted and explicitly disabled controls.
These corrections and the newly added namespaced/plugin controls await their
later native runs; they are not credited from the failed run.

Run `34653259288` on `713da12` passed 96 combined-stage tests and failed two
positive controls before a second provider request. The downloaded artifact
`m8-containment-34653259288-1` independently establishes thirteen complete native
tool cases: both physical-worker paths, all direct refusal paths, both image
positives, and the gpt-5.5 patch positive. Worker callbacks each have one raw
owned worker outcome, successful decoded result, matching RPC/peer identities,
and no post-join peer failures. The artifact's original catalog, restricted
catalog, and binary hashes retain the published pins.

The remaining first-request mismatches were original Sol agent context and
enabled-plugin guidance, not tool failures. Both have independent sources named
above. The source-backed expectations now retain them only in those deliberate
positive controls; completion awaits a later exact-head run rather than being
inferred from a corrected first-request comparison.

The same artifact has two untrusted and two disabled hook observations with
zero hook events, plus two trusted attempts with paired start/completion and
the exact `ENOENT` failure. Independent review found that the untrusted test
had checked only the marker. The correction checks the exact event sequence
in all three states. A portable whole-test reproduction and a call-site mutant
prove that an attempted-but-failed untrusted hook cannot pass as disabled.

The repository gate on `713da12` passed locally (1,993 tests, 342 platform skips)
and on CI (2,067 tests, 268 skips), with ruff, strict mypy and four import
contracts. That green gate does not erase the two native failures. Final-head
local/CI/native gates, artifact inspection and independent confirmation remain
required by PR #58; the source corrections alone do not establish them.

## Origin/control inventory and qualification boundary

The origin matrix runs on gpt-5.5; fresh baselines and tool/worker cases run on
both pinned profiles. The table is deliberately narrower than a claim about
every extension or every CLI startup mode.

| Origin | Control and evidence | Qualification limit |
| --- | --- | --- |
| Packaged assets/model metadata | Immutable inventory, pinned binary and both catalog hashes; fixed model selection | Not an audit of all embedded behavior or other models |
| System/managed sources | Curated image excludes `/etc/codex`; bootstrap absence and null requirements observed | Managed-policy execution positive is unexecuted |
| User/profile layers | Private controller config; unused profile ignored; selected profile refused before RPC | Named-profile app-server use is refuted, not supported |
| Project/ancestor state | Private cwd, no acquired repo mount; trusted/untrusted project TOML plus inert MCP | Does not authorize arbitrary project startup content |
| Environment | Owned launch clears inherited state; exact child environment recorded | Older host-poison test remains separate startup evidence |
| Skills | User/project positive discovery, explicit instruction/bundled controls, exact request comparison | Installation and arbitrary skill behavior are unexecuted |
| Hooks | JSON/TOML discovery, exact trust hash, no-event untrusted/disabled observations, failed trusted attempts | Successful command-hook execution blocked by missing default shell |
| Local plugins | Explicit enablement of one seeded cache entry; skill identity and MCP/public-marker control | Installer/marketplace workflows unexecuted; enabled completion requires final run |
| MCP/apps | Project-trust MCP positive and absent counterpart; exact resource-tool golden; apps disabled | Account-backed apps and arbitrary server behavior unexecuted |
| Cloud/account/cache | Fresh private home, null account, no provider credentials | Authenticated or cloud-managed state unexecuted |
| RPC and worker | Fixed controller scenario, bounded wire, actual acquired READ worker, full outcomes | No native journal/RunHost/revocation recovery proof |
| Request sender | Actual contained non-native descendant uses bridge then direct leaf with exact bytes | CLI-authorship inference is refuted; invocation membership only |

The deliverable is this bounded evidence and its regression suite, not an
authentication design. Proved local facts, refuted hypotheses, unexecuted cloud
surfaces, and the hook-shell prerequisite remain separate. A passing final
regression run does not remove the qualification boundary. Native authentication
and durable recovery stay unavailable pending their accepted prerequisites and
the owner's decision in [#38](https://github.com/sushiHex/constructicon/issues/38).

## Investigation closure

PR #58 squash-merged as `489db82fdf200502956e4c54aaa2c09cede598a9` and
closed #57. Its tree equals reviewed `574c424abacb1fac12b85190b47a32d1dcfcfdb9`.
That head passed local verification (2,000 tests, 342 platform skips), CI,
105 combined-stage tests and 16 assertion mutants. Independent source and
downloaded-artifact review found no remaining blocker at this stated scope.
Artifact `10284874908` from
[run 34654341443](https://github.com/sushiHex/constructicon/actions/runs/34654341443)
contains all fourteen completed tool cases, fifteen completed origin records,
the named-profile refusal, both actual worker controls and both descendant
sender controls. The seeded enabled-plugin control completed; installation
remains unexecuted. No qualification limit above is erased by closure.

The successful-hook gap has one separately scoped
[follow-up](M8-hook-execution-evidence.md). It tests the already-packaged shell
without rewriting the failed default-shell observation or modifying this
investigation's approved acceptance. Native authentication and recovery remain
gated; #38 still records no selected route.
