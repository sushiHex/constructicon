# M8 N5: the native tool inventory

Status: design, independently reviewed once (Codex `gpt-6-sol`, job
`job_1e39d303f2d5`) and amended; see [Review disposition](#review-disposition).
Credential-free; nothing here qualifies a destination, runs a subscription turn
or makes the provider available.
Base: `c8769af`. Branch: `feat/n5-native-inventory`.
Scope: the Stage 0b open item recorded in the
[M8 implementation record](M8-implementation-record.md): the native
`apply_patch` tool survives the production recipe. Measured on the real binary,
the gap is wider; this document closes all of it before Stage 3 (READ).
Authority:
[ADR 0020](../../adr/0020-native-harnesses-mediate-contained-tools.md) lines
102-111, unchanged: "The native catalog for an available profile contains
exactly the admitted callback tool set. ... A configuration flag or empty list
alone is not that proof."

Pinned source: `openai/codex` tag `rust-v0.160.1`, commit `d27764b8`. Paths are
relative to `codex-rs/`.

## Findings

### The catalog overrides the configuration

The sealed model `gpt-6.1-sol` carries three tool selectors in the pinned
catalog (`models-manager/models.json`):

| Field | Value | Effect |
|---|---|---|
| `apply_patch_tool_type` | `"freeform"` | registers `apply_patch` whenever an execution environment exists (`core/src/tools/spec_plan.rs:1269`) |
| `tool_mode` | `"code_mode_only"` | wins over every feature flag (`core/src/tools/mod.rs:76-86`): `code_mode = false` does nothing |
| `multi_agent_version` | `"v2"` | wins over `multi_agent = false` (`core/src/config/mod.rs:1586-1613`) |
| `experimental_supported_tools` | `["send_user_message_async", "clock"]` | registers `request_user_input_async` and the `clock` tools (`spec_plan.rs:1178-1251`) |

Two more tools are on by default and untouched by the recipe:
`request_user_input` (`core/src/config/mod.rs:2705-2711`) and image
generation (`features/src/lib.rs:1553-1556`), whose gate opens for the OpenAI
provider with ChatGPT auth (`spec_plan.rs:727-763`).

`apply_patch_freeform` and `js_repl` are removed features
(`features/src/lib.rs:1046`, `:1196`); nothing reads them. They are dead keys,
not controls.

### Measured: what production offers today

The placement lane ran the production configuration, swapped only for its
provider and catalog path, against the real 0.160.1 binary, and read the first
model request (CI run 37614544749, `#126` at `bbd5a88`). Names are as offered;
`exec>` marks a tool nested in code mode's `exec`:

| Namespace | READ and WRITE |
|---|---|
| `functions` | `exec`, `wait`, `request_user_input`, `request_user_input_async` |
| `functions.exec>` | `apply_patch`, `clock__curr_time`, `image_gen__imagegen` |
| `clock` | `sleep` |
| `collaboration` | `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `interrupt_agent`, `list_agents` |

WRITE adds `contained_python`, and only as `functions.exec>contained_python`:
in code mode the admitted callback is itself reachable only through `exec`.
Fourteen native tools in all; the rule admits none.

## Design

Three layers, each closing what the others cannot, each at a seam that already
exists. None changes the host installation: the launch set keeps the vendor's
pinned bytes, and the planner, `verify-launch`, the bump tool and the runbook
are unchanged.

### The native layout belongs to the launcher

The zone already receives `config.toml` as a sealed memfd bound with
`--ro-bind-data` (`sealed_data_fd`, `linux.py:290`). The sealed catalog and
`environments.toml` reach it the same way, but the launcher makes them: their
content is fixed by `linux.py`, so no caller can choose it, as
`NativeStoreMount` already promises ("never a caller-selected mount
catalogue", `linux.py:222`). A `NativeLayout` holds the two sealed descriptors
for one launch; `_launch` creates it for a native-store launch, `argv` binds
it, and it is closed after the exchange.

Identity: both live in `linux.py`, whose bytes the launcher's revision digests
(`"recipe": _sha(Path(__file__))`, `linux.py:478`), and every lane's evidence
records that revision (`launch_revision`). That binds the code, not its output,
so evidence also records `executable.sealed_catalog_sha256`, and
`check_evidence` recomputes it from the launch set's installed catalog beside
`executable.catalog_sha256`, the source's digest.

### 1. The sealed catalog

`sealed_catalog(source) -> bytes`, applied to **every** entry so a pin bump
that moves the sealed choice stays covered:

```json
"apply_patch_tool_type": null,
"tool_mode": "direct",
"multi_agent_version": null,
"experimental_supported_tools": []
```

`tool_mode` is written as `"direct"`, never omitted: an unknown or missing
value falls back to the feature flags (`openai_models.rs:352-361`). Nothing else
changes: no slug, instruction, effort or visibility. The installed catalog stays
the vendor's pinned bytes, checked by custody as now (`NativeVendor.check`), and
is the transform's only input. Cost: one parse of a 472 KB document per launch.

### 2. The configuration

`production_configuration()` ends with the tool controls:

```toml
image_generation = false
sleep_tool = false
multi_agent_v2 = false
[features.tool_registry]
error_on_tool_collisions = true
[agents]
enabled = false
[tools.experimental_request_user_input]
enabled = false
```

- `[agents] enabled = false` forces multi-agent off whatever the catalog says
  (`core/src/config/mod.rs:1589-1590`, `:1606-1613`). Only the
  `multi_agent_v2` feature outranks it (`:1586-1588`); it is off by default
  (`features/src/lib.rs:1337-1341`) and pinned off here.
- `sleep_tool` is on by default (`features/src/lib.rs:980`); the catalog layer
  already removes it with `clock`, so this holds it if a later catalog
  re-adds `clock`.
- Dispatch is a registry lookup that never checks the tool was offered
  (`core/src/tools/registry.rs:551-573`), and a duplicate external name is
  skipped silently, first registration winning (`:398-411`). Dynamic tools
  register last (`spec_plan.rs:174`), so a native tool named
  `contained_python` would own the name. `error_on_tool_collisions` fails the
  turn instead (`spec_plan.rs:421-425`).
- `apply_patch_freeform` and `js_repl` are removed from the configuration.

The rule for which gates the configuration pins: every default-on gate of a
model-visible tool. Default-off gates (`update_plan`, token budget,
`send_message_to_user_async`, `request_permissions`) are held by the
inventory lane, which fails on the bump that flips one.

### 3. No execution environment

`$CODEX_HOME/environments.toml`, one line:

```toml
include_local = false
```

With no `default` and `include_local = false`, the default is `Disabled`
(`exec-server/src/environment_toml.rs:236-248`) and `local` is not
selectable; the file is parsed with `deny_unknown_fields` (`:27-33`), so a
damaged file fails startup. Without an environment, no environment-backed tool
registers: `apply_patch`, `view_image`, `exec_command`, `write_stdin`,
`request_permissions`. This is the structural layer: it holds even if the
catalog drifts. Dynamic tools register regardless (`spec_plan.rs:174`,
`:1426-1456`), so WRITE keeps `contained_python`.

### What remains

| Recipe | Offered tools |
|---|---|
| READ | none |
| WRITE | exactly `functions.contained_python`, as the adapter declares it |

## Proof

The placement lane runs the real binary against the fake provider with the
production configuration, swapped only for its provider and catalog path
(`tests/native_inventory.py`). Its image carries the pinned catalog and its
`sealed_catalog`, made by the production function. The probe provider sends the
actor-authorization fixture header so the image-generation gate opens on
loopback as it does in production (`model-provider-info/src/lib.rs:621-629`).
Initialize, the thread and the turn are the adapter's own requests for each
mode.

1. **The rule, by schema.** Sealed, the first request's offered tools equal a
   closed golden, compared as JSON, not names: READ `[]`; WRITE the
   `contained_python` declaration exactly.
2. **The callback works without an environment.** In the sealed WRITE case the
   provider calls `contained_python`, the lane answers the callback, and the
   second request carries exactly that output; the turn completes.
3. **Every known native name is refused.** Sealed, the provider calls each name
   the baseline offered, and each environment-backed tool, once per case; the
   next request carries `unsupported call` for it and nothing else ran.
4. **Each layer holds its own tools.** Offered names equal a closed golden per
   case:

   | Case | Shows |
   |---|---|
   | without the sealed catalog | code mode, `clock`, collaboration and `request_user_input_async` return, without `apply_patch` |
   | without the catalog or the environment file | `apply_patch` returns too: the environment layer held it alone |
   | without the configuration's tool controls | `request_user_input` and image generation return |

The real-launcher startup lanes start with the new configuration, sealed
catalog and environment file at their production paths, which proves strict
acceptance and parse on the real layout. Portable tests pin `sealed_catalog`
to change exactly the four fields of every entry, and the argv to bind the
layout.

A pin bump reruns the lane; a catalog field or default that adds a tool fails
it. That is the tripwire that keeps updates seamless.

### What the lane cannot see

- **Later requests.** Only the first request's offer and one continuation are
  measured. Production compacts remotely (`RemoteCompactionSupport::V2` for the
  OpenAI provider, `model-provider/src/provider.rs:461-473`); the probe
  provider cannot. Whether a remote compaction rebuilds the tool offer is
  UNVERIFIED and left to the Stage 3 READ evidence.
- **Account-dependent gates.** The image gate also reads the account plan
  (`spec_plan.rs:737-746`); the fixture header stands in for ChatGPT auth. The
  configuration closes the gate whatever the plan.
- **Unknown hidden tools.** Refusal probes cover every name known at this pin;
  a registered, hidden tool with a new name would not be found by them.

## Side effects

- **Model behavior.** The model was tuned for code mode; its base
  instructions still mention `functions.exec`, `clock.sleep` and
  `spawn_agent`. An absent tool's call returns "unsupported call". This is a
  quality risk for Stage 3, not a containment one.
- **No environment changes the request context.** Project `AGENTS.md` is not
  loaded; the environment-context text changes.
- **The image-generation extension stays installed.** The feature removes the
  tool, not the extension.

## Not in scope

The test transform `catalog_for` (`tests/native_codex_probe.py`) keeps serving
the older probe lanes; unifying it with `sealed_catalog` would move their
goldens and is not needed here.

## Review disposition

One Codex pass (`gpt-6-sol`, `xhigh`, job `job_1e39d303f2d5`) on the draft.

Adopted:
- **Dispatch never checks the offer** (`registry.rs:551-573`): name equality
  does not prove that only the offered tools run. Added refusal probes for
  every known name (proof 3), schema equality (proof 1) and collision failure
  (configuration).
- **The callback without an environment was unproved** (the draft lane
  permitted no tool call): added proof 2.
- **The mount contract was underspecified, and the recipe digest binds code,
  not output**: the layout is now launcher-owned (`NativeLayout`) and evidence
  records and rechecks the sealed catalog's digest.
- **Default-off gates are not closed by the catalog**: recorded the rule for
  which gates the configuration pins and that the lane holds the rest.
- **Remote compaction and account gates are outside the lane**: recorded under
  [What the lane cannot see](#what-the-lane-cannot-see).

Rejected: nothing. Install-time derivation, which the review weighed against
per-launch derivation, would add a separately installed artifact to custody,
verification and the runbook; per-launch derivation keeps the launch set
byte-identical to the vendor's pins.
