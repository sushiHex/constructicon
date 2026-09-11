# M8 controlled startup: investigation evidence

Status: work in progress; native checks below are prospective until an
exact-head Actions artifact is recorded. No production profile is qualified.

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

`LinuxLauncher.exchange` now supports native startup RPCs, with the same
supervisor, guards, capture bounds, deadline, and namespace recipe as batch
work. `DuplexWire` frames its byte chunks through the existing investigation
`Wire`; it introduces no process owner or second JSON/RPC validator.

A separate immutable **test image** copies the already-curated userspace and
adds the pinned CLI package, restricted catalog, and a small setup entry point.
Its content participates in the normal runtime and launch digests. It is not
the original runtime image and does not inherit its exact artifact identity.
The entry point receives one trusted setup record, writes only private `/tmp`
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

The table deliberately separates candidate controls from executed proof.
Native tests live in `tests/substrate/test_native_startup.py`; until their
artifact is recorded below, every native result is **unexecuted**.

| Origin | Candidate control / observation | Test or remaining gap |
| --- | --- | --- |
| Packaged defaults and assets | Whole pinned package in immutable runtime | Record native layers and full runtime inventory; not an audit of every embedded behavior |
| System and legacy-managed files | No `/etc/codex` in curated image | Bootstrap checks physical absence; native layers recorded; no managed-policy positive control yet |
| Cloud config, auth, prior-session caches | Fresh private home; no account or route | Absence by construction; authenticated/cloud configuration remains unqualified |
| Base user config | Controller-created private config before exec | Both pinned models; exact native `config/read` results |
| Selected user/profile config | Controller owns argv and private files | Explicit session override positive control; named-profile precedence unqualified |
| Working directory / ancestor / repository | Fresh private cwd; no acquired repo mount | Absent workspace metadata; project-skill positive/absent control; project TOML/trust matrix unqualified |
| Environment / internal overrides | Existing `--clearenv` plus three fixed variables | Poisoned host `CODEX_HOME`, base URL, and debug override absent from child and native result |
| Skills | Fresh roots; embedded assets bound to binary | User/project inert skill positive/absent controls and native inventory |
| Hooks, plugins, MCP, apps | No inherited configuration; same published tool controls | Baseline hook inventory only; execution order, plugin/MCP discovery and startup-process matrix remain unqualified |
| Model/runtime metadata | Pinned package/catalog, two exact model selections | Native config/layers recorded; full request-tool inventory still has only the separate PR #50 lab proof |
| Client RPCs | Trusted bounded `Wire` requests, same refusal law | Portable framing, malformed/foreign messages, byte ceilings; not model-selected authority |

## Verification and decision boundary

Portable checks exercise framing, exact JSON/RPC refusals, send/receive bounds,
and fixed configuration. Windows skips are not physical proof. Native checks
must record process exits, timeout/bound flags, warnings, runtime identity,
the exact config layers and discovery responses. The provider test starts the
existing credential-free fake endpoint outside the launch namespace and
records its empty request list plus the native failed turn. That is a negative
connectivity observation, not a successful native model invocation.

Required gate: exact-head `uv run verify`, CI, relevant assertion mutants,
independent review, and separate inspection of the downloaded artifact.
No passing expected-refusal test closes the positive combined qualification.
Startup completeness and the supported provider arrangement must be established
before native SQLite/RunHost recovery can begin. No successor ADR, credentials,
paid API substitution, or live availability follows from this record.

Exact-head native results and review: **not yet executed**.
