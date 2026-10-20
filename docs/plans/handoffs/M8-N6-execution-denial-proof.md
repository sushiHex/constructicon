# N6 — execution-denial feasibility evidence

Investigation for [#175](https://github.com/sushiHex/constructicon/issues/175),
under [ADR 0021](../../adr/0021-subscription-executors-bind-operator-stores.md).
This is an independent, credential-free enforcement experiment, not a Claude
launch profile or a permitting startup predicate. The accepted N6 plans and
existing production launch policy are unchanged.

## Question and scope

Can a mandatory Linux profile admit one fixed initial executable, then forbid
subsequent executable launches by that process and its descendants?

The proposed experiment uses a fixed benign native fixture, not a vendor
binary. A directed AppArmor transition without an inheritance or unconfined
fallback enters a separate payload profile. That profile permits the fixture's
ordinary operations but no subsequent executable launch. A missing transition
target must refuse the initial launch rather than run an unconfined payload.

The distinction between executable mapping and execution is intentional:
AppArmor's `m` permission permits executable memory mappings; `x` governs
executable launches. This experiment does not claim to prevent computation,
JavaScript evaluation, library calls, or work performed by an already-running
interpreter. See the upstream [AppArmor policy reference](https://www.apparmor.net/man/4.0/apparmor.d/).

## Required observations

The permitting control must exchange fixed bytes and report the exact enforcing
payload label. Denial controls cover ordinary execution, shell execution,
self-execution, execution through a file descriptor, and a forked descendant.
Executable targets must also succeed in an unconstrained control: missing
files, unsupported system calls, or an invalid fixture are not denials.

The fixture also performs harmless in-process file and socket operations.
Their success makes the limitation observable: execution denial does not
separate credentials, provider traffic, and other code in one native process.
No credentials, provider endpoints, vendor binaries, or private host are used.

The controller owns a bounded process group and joins it before policy or
fixture cleanup. Its launch, timeout, failure, and cleanup paths are part of
this experiment, not evidence for Constructicon's production launcher. A
missing result or an unknown, absent, or non-enforcing label must refuse proof.

## Composition boundary

Even a successful physical experiment establishes only execution denial.
Claude's managed environment, in-process hooks, MCP clients, authentication
selection, and pre-dispatch model paths still need their own source-grounded
restrictions. The native/worker/store/egress lifecycle must subsequently be
qualified as one coherent recipe. No `startup_ok` value, accepting READ
fixture, or production availability follows from this proof alone.

Current source investigation and ownership remain on #175. A change to the
accepted authority contract requires an explicit successor decision, not a
relabeling of this partial result.

## Source findings that bound the experiment

The parallel source review retains CLI 2.1.296 and SDK 0.3.296, with the
[N6a artifact identities](M8-N6a-state-review.md). These observations come from
reading embedded source, not executing the client. `B@` denotes a zero-based
offset in that pinned Linux member.

- A documented embedding-host switch is not a store-preserving shortcut.
  `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST` protects provider/authentication
  settings, but `F$` at `B@210424026` returns before stored OAuth discovery
  when `on()` is true; `on` at `B@210386049` includes this switch. The review
  rejected substituting externally supplied tokens for the accepted opaque
  native store. The switch is documented; calling it undocumented would be
  inaccurate. Its semantics, not its name, disqualify this use.
- A narrower temporal candidate deserves examination rather than a blanket
  requirement for immutable environment variables. The documented
  `forceRemoteSettingsRefresh` setting is required when any admin tier sets
  exact `true` (`B@209451245`, `B@209140167`). PreAction awaits its fetch
  (`B@225716789`). The subsequent poll uses a one-hour interval
  (`B@224541344`, `B@215247456`, constant `B@224508568`). A total deadline
  below that interval, beginning at spawn, can exclude this particular
  polling route. This is not proof against other settings changes, pending
  helper work, or values already applied during startup.
- Settings inspection is not process-environment inspection. `get_settings`
  (`B@233738416`) returns a settings projection through `NTr`
  (`B@209450024`); environment applicators assign values without clearing
  removed keys. A clean-looking settings response cannot alone prove the
  effective authentication or feature state of the running process.
- Ordinary managed hook JSON cannot construct function/callback objects:
  its union covers command, prompt, agent, HTTP and MCP-tool hooks. Ordinary
  SessionStart lacks messages/tool context, so the function, prompt and agent
  branches refuse before their helpers. This is not the whole hook system:
  classic builtin modules can run in the same thread or a Bun Worker, which
  execution denial does not stop.
- Two retained builtin paths were narrowed by their actual branches. Diff's
  `Yr` (`B@243206318`) examines messages and only calls `Wt`
  (`B@243206047`) when parsed file changes exist; the latter also requires
  fullscreen UI state. Telemetry's `Me` (`B@243261307`) checks suppression
  before authorization or HTTP. Fresh history and effective suppression are
  explicit premises, not facts supplied by this physical experiment.

The orchestrator independently read the stored-login refusal, awaited refresh,
diff continuation and telemetry guard. Other bounded provenance traces and
their limits are recorded on #175. No end-to-end startup clearance is claimed.

## Portable evidence and review

The initial implementation passed 96 portable tests, including real subprocess
exchange and interrupted/expired-exchange joins. Eight guard mutants were
assertion-killed after their passing controls. A first inventory invocation
refused credit because concurrent documentation edits changed its source
snapshot; only the subsequent frozen-tree run is counted. New Python files
passed Ruff; the Linux-specific driver passed strict mypy with Linux as its
target platform. Independent source review found no blocking introduced defect.

These results do not include C compilation or AppArmor enforcement on Windows.
The foundation CI step must produce the physical result before either is
reported as measured. The uploaded `m8-noexec.json` distinguishes this
standalone experiment from production availability and Claude qualification.
