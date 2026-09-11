# M8 controlled startup: investigation evidence

Status: partial native observations; combined qualification is blocked.
Exact-head readiness is tracked in PR #54. No production profile is qualified.

Base: `6d6379c56bc1dd44a6f32f82b00efefbefdbe939` (merged PR #53).
The owner authorized the four recommended steps: transport-record closure,
startup inventory/proof, supported native fixture placement, and a reviewed
qualification PR. [#37](https://github.com/sushiHex/constructicon/issues/37)
owns this investigation; [#38](https://github.com/sushiHex/constructicon/issues/38)
owns the eventual authentication decision. The approved
[qualification plan](M8-native-qualification-plan.md) and
[ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md)
remain unchanged. Durable native recovery is not in this slice.

## One owner, two different questions

`LinuxLauncher.exchange` carries native startup RPCs, with the same
supervisor, guards, capture bounds, deadline, and namespace recipe as batch
work. `DuplexWire` frames its byte chunks through the existing investigation
`Wire`; it introduces no process owner or second JSON/RPC validator.

A separate immutable **test image** copies the already-curated userspace and
adds the pinned CLI package, restricted catalog, and a small setup entry point.
Its content participates in the normal runtime and launch digests. It is not
the original runtime image and does not inherit its exact artifact identity.
The existing duplex test helper supplies a real acquisition guard. This is
not a journal lease or evidence of native RunHost recovery. The entry point
receives one trusted setup record, writes only private `/tmp`
files, and replaces itself with the native app-server. It never spawns or
supervises another controller. No acquired repository is mounted.

The production launcher, AppArmor profiles, network/grant schema, and executor
profiles are unchanged. This arrangement can observe startup; it cannot supply
a remote model route. The existing fake Responses endpoint is outside the
fresh network namespace. Bringing a listening peer into a different namespace,
enabling loopback, mounting a route, or treating the native CLI as a newly
trusted host principal would require a separately justified arrangement or
decision. This experiment does none of those things.

## Pins and sources

Linux release remains `0.153.4`; package SHA-256
`a822187e1a2420c61c5926721bfbd878701ed95547c9bb0d4de4498a16ba1821`.
Upstream source remains
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`; catalog SHA-256
`d7136a413cfac1b5b1686d9e0dcc5c80ca05bebed5e9fc3911376561d0ef6ee8`.
The same two entries, `gpt-5.5` and `gpt-5.6-sol`, retain the three explicitly
reviewed tool-selector changes from PR #50. `catalog_for` is shared by the
original mediation fixture and this image builder, not reimplemented.

Current [configuration documentation](https://learn.chatgpt.com/docs/config-file/config-basic)
is orientation, not evidence for this pinned release. The source below was
read at the exact commit; it is not a claim of release execution:

- [Configuration loader](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/config/src/loader/mod.rs)
  inventories packaged, system, managed, cloud, user/profile, project, and
  runtime layers. Packaged defaults are embedded when no override is given.
- [Executor-local loader](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/config/src/loader/local.rs)
  uses system/base-user/project and legacy-managed sources, not selected
  profiles, session flags, or the cloud stack. One high-precedence setting
  cannot stand in for controlling every reader.
- [App-server entry point](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server/src/lib.rs)
  gates `CODEX_APP_SERVER_TEST_USER_CONFIG_FILE` behind debug assertions.
  This release experiment does not rely on that internal override.
- [Hook discovery](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/hooks/src/engine/discovery.rs)
  reads both layer-relative `hooks.json` and TOML hooks, managed requirements,
  and plugin hook sources. Empty user TOML alone is not a hook inventory.
- [Published startup queries](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/config.rs)
  expose config and its origins/layers;
  [skills/hooks queries](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/app-server-protocol/src/protocol/v2/plugin.rs)
  expose separate discovery surfaces. A returned inventory is not a proof
  that arbitrary hooks cannot execute before validation.

## Origin to control to test inventory

The table separates scoped observations from remaining qualification gaps.
Native tests live in `tests/substrate/test_native_startup.py`. The first
executed observations are recorded below; no row borrows credit from an
unexecuted control or from a different native fixture.

| Origin | Candidate control / observation | Test or remaining gap |
| --- | --- | --- |
| Packaged defaults and assets | Whole pinned package in immutable runtime | Record native layers and full runtime inventory; not an audit of every embedded behavior |
| System and legacy-managed files | No `/etc/codex` in curated image | Bootstrap checks physical absence; native layers recorded; no managed-policy positive control yet |
| Cloud config, auth, prior-session caches | Fresh private home; no account or route | No inherited account files; authenticated/cloud configuration remains unqualified |
| Base user config | Controller-created private config before exec | Both pinned models; exact native `config/read` results |
| Selected user/profile config | Controller owns argv and private files | Explicit session override positive control; named-profile precedence unqualified |
| Working directory / ancestor / repository | Fresh private cwd; no acquired repo mount | Absent workspace metadata; project-skill positive/absent control; project TOML/trust matrix unqualified |
| Environment / internal overrides | Existing `--clearenv` plus three fixed variables; bubblewrap supplies `PWD` | Poisoned host `CODEX_HOME`, base URL, and debug override absent from child and native result |
| Skills | Fresh roots; embedded assets bound to binary | User/project inert skill positive/absent controls; packaged system skills materialize in the fresh home |
| Hooks, plugins, MCP, apps | No inherited configuration; same published tool controls | Baseline hook inventory only; execution order, plugin/MCP discovery and startup-process matrix remain unqualified |
| Model/runtime metadata | Pinned package/catalog, two exact model selections | Native config/layers recorded; full request-tool inventory still has only the separate PR #50 lab proof |
| Client RPCs | Trusted bounded `Wire` requests, same refusal law | Portable framing, malformed/foreign messages, byte ceilings; not model-selected authority |

## Executed observations and corrected assumptions

The first two runs failed before native launch: the instrument first omitted
the required guard argument, then supplied an empty tuple. Both are invalid.
It now reuses the guarded duplex test helper; a portable test pins that
interface using a fake guard, and the native lane takes the real Linux guard.
Neither failed run supplies native execution evidence.

At `236068c843cb8280abeb2f30adeb15bd9022efab`,
[run 34581074023](https://github.com/sushiHex/constructicon/actions/runs/34581074023)
passed eight startup assertions and failed the ninth test's incorrect
expectation of a completed failed turn. Its downloaded artifact was inspected
independently of those assertions:

- Both models return their private config and origins through native RPCs.
  User config names `/tmp/home/.codex/config.toml`; the system layer is empty.
  The bootstrap environment includes bubblewrap's `PWD=/tmp`, in addition
  to the launcher's fixed `HOME`, `PATH`, and `LANG`.
- The poisoned outer environment is absent. A controlled session override
  changes the native model; unknown feature/table settings refuse startup.
  Inert user/project skills appear only in their positive controls.
- A fresh home is not an empty native startup: packaged system skills are
  installed there. `hooks/list` returns an empty baseline, not a hook-execution
  proof. `configRequirements/read` returns null, not managed-policy proof.
- Native startup warns about missing bubblewrap on its internal PATH and
  refusing helper aliases under `/tmp`. These warnings are retained. No extra
  binary is installed simply to silence them. The outer Constructicon launcher
  is the enforced boundary; this is not proof of native sandbox execution.
- The native config projection names the external fake endpoint. Thread and
  turn creation succeed, followed by typed errors: `Connection failed: error
  sending request` and `Reconnecting... waiting for network`, with
  `willRetry=true`. Both provider retry settings were zero. No terminal turn
  arrives; at 20 seconds the existing owner terminates the payload with status
  143 and `timed_out=true`, with no capture-bound violation. This is a bounded
  network-failure observation, not a graceful native refusal or successful
  provider exchange.

The corrected regression requires the matching thread/turn error identities,
the native endpoint projection, empty external request/failure lists, and the
actual timeout outcome. It never converts an unfinished turn into completion.
The older PR #50 fixture still tests a working fake provider in its separate
outer lab namespace. That positive result is not connectivity for this image.

At `016eca5a3f0db21b11d81a1f76d23f5ce8f41ff8`, the corrected
[native lane](https://github.com/sushiHex/constructicon/actions/runs/34581593946)
passed all nine startup cases, 87 existing mediation cases, 324 containment
cases, and 142 assertion mutants. The
[CI repository gate](https://github.com/sushiHex/constructicon/actions/runs/34581593968)
passed 1,916 tests with 223 explicit skips. Downloaded host metadata names
that head; the runtime digest was independently recomputed from its inventory,
and the catalog, bootstrap, and binary entries match the pinned source
projection, committed bootstrap bytes, and pinned package executable.

The [independent review](https://github.com/sushiHex/constructicon/pull/54#discussion_r3987643307)
found one evidence-gate defect: `None != 0` allowed a missing private payload
exit to count as strict-config refusal. The actual native artifact has exit 1;
the assertion, not that observation, was wrong. A portable regression first
failed on missing evidence, then passed after requiring both observed statuses
to be 1 with no timeout or capture-bound failure. Its fake result is only an
assertion test, not native provenance. A new mutant removes the payload check.

## Verification and decision boundary

Portable checks exercise framing, exact JSON/RPC refusals, send/receive bounds,
and fixed configuration. Windows skips are not physical proof. Native checks
must record process exits, timeout/bound flags, warnings, runtime identity,
the exact config layers and discovery responses. The provider test starts the
existing credential-free fake endpoint outside the launch namespace and
records its empty request list plus the native nonterminal retry and bounded
termination. That is a negative connectivity observation, not a successful
native model invocation. Patch/image/model-dependent tool inventories cannot
be re-proved through this arrangement without a working provider fixture.

Required gate: exact-head `uv run verify`, CI, relevant assertion mutants,
independent review, and separate inspection of the downloaded artifact.
No passing expected-refusal test closes the positive combined qualification.
Startup completeness and the supported provider arrangement must be established
before native SQLite/RunHost recovery can begin. No successor ADR, credentials,
paid API substitution, or live availability follows from this record.

The remaining decision is a supported credential-free provider-fixture
arrangement that preserves one physical owner and names its precise network
boundary. The present HTTP listener is outside `--unshare-net`; moving the CLI
outside containment, enabling a route, or starting another owner is not an
implicit next step. No blanket claim that every possible supported arrangement
is impossible follows from this one negative result. Until that prerequisite
and the remaining startup-origin controls are resolved, Slice B stays blocked.

Final merge-head verification and review links belong in PR #54. Readiness
must come from that head's gates, never from the earlier runs recorded here.
