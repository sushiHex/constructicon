# Executor authentication: feasibility and next decision

Status: evidence and recommendation, updated 2026-09-12; not an accepted ADR or a
claim of working subscription integration. No login, credential inspection,
remote provider request, or gateway provisioning was performed.

## Current qualification decision

This section is the current packet; the dated sections below preserve how the
evidence changed. [#38](https://github.com/sushiHex/constructicon/issues/38)
owns the authentication decision. The owner authorized the bounded startup
gate review in [#61](https://github.com/sushiHex/constructicon/issues/61),
followed by a separate durable-recovery slice **only if that gate passes**.
This is not acceptance of a successor to ADR 0018.

The baseline is `77da3f6db20bc98a43939822f7cc441755a2a95e`, the squash
merge of [#60](https://github.com/sushiHex/constructicon/pull/60), tree-equal to
reviewed `92ec3c2bd6df15197277abca2cb0fddf4e2e4b9f`. Its exact-head Linux
[run 34659442292](https://github.com/sushiHex/constructicon/actions/runs/34659442292)
produced artifact `10287620781`: 131 combined-stage, 87 mediation and 324
containment tests passed, including all 29 combined assertion mutants.
The earlier [#58](https://github.com/sushiHex/constructicon/pull/58) result
remains partial; neither merge claims native authentication or recovery.

### One finite candidate

The candidate remains the credential-free **test fixture**, not a production
profile or a credential-owning process outside containment. It is defined by
[`controlled_configuration`](../../tests/native_combined.py), the immutable
[`startup bootstrap`](../../tests/substrate/_native_startup_bootstrap.py),
the [accepted placement](../plans/handoffs/M8-provider-fixture-proposal.md),
and the pinned Codex 0.153.4 source
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`.

- Keep the exact package, restricted catalog, runtime and two model-profile
  pins from #60. Model names select local metadata; no model is contacted.
- Start `app-server --strict-config --stdio` in a newly created private home
  and cwd, not the acquired repository. Only the contained worker receives
  the repository. No login files, prior session, host home or journal is
  mounted into the native process.
- The trusted driver writes the configuration and sends the bounded RPC
  sequence. Model-supplied arguments do not select configuration, RPC methods,
  the provider endpoint or process launch. The fixed fake peer uses no incoming
  request as an instruction or response-script selector.
- Keep `shell_zsh_fork=false` in the baseline. #60's true variant is an
  experimental **positive control**, proving that exact trusted hooks really
  execute while their untrusted/disabled counterparts do not attempt to run.
  That variant's warning and `underDevelopment` stage remain evidence; it is
  neither needed by the empty baseline nor promoted to production support.
- Keep the actual effective feature distinction: configured
  `unified_exec=false` is normalized true on this release, but
  `shell_tool=false` gates registration. The independent exact tool/context
  checks and attempted-call refusals, not the requested flag, carry the proof.

### Origins and evidence limits

These rows classify the candidate, not all deployments of the native CLI.
The detailed observations remain in the
[combined record](../plans/handoffs/M8-combined-startup-evidence.md) and
[hook record](../plans/handoffs/M8-hook-execution-evidence.md).

| Origin | Candidate control and observed evidence | Not qualified by it |
| --- | --- | --- |
| Runtime and model metadata | Root-owned content inventory; pinned package and controller-selected restricted catalog; patch/image/model-dependent controls | A different release, catalog, or runtime |
| System/managed config | Curated runtime has no `/etc/codex`; cleared environment; requirements query is null | A managed deployment or its authenticated policy |
| User/profile, project and ancestors | Fresh private paths; controller-owned files/argv; unused-profile, selected-profile refusal, project trust and MCP controls | Inherited desktop configuration or repository cwd |
| Environment | Exact cleared environment observed by the bootstrap; no inherited host credentials or loader variables | Arbitrary environment inheritance |
| Hooks | No baseline hooks; JSON/TOML discovery and trust controls; four real executions and eight no-attempt packaged-shell counterparts | Enabling arbitrary hooks or treating ENOENT as disablement |
| Skills and plugins | Fresh private roots, bundled/prompt skill controls; explicit seeded-plugin enablement and discovery controls | Plugin installation, marketplace workflows, arbitrary extensions, or a claim that the plugin subsystem is disabled |
| MCP/apps | No baseline server, apps disabled; inert trusted-project and seeded-plugin startup controls | Arbitrary servers or authenticated apps |
| Account/cloud/session state | Fresh account-empty home and bounded local fake provider; no external route | Authenticated/cloud-managed behavior, real provider conformance, or subscription availability |
| Protocol and callback | Trusted bounded driver, exact peer conversation, real contained-worker result | CLI sender authentication: a contained descendant can also use the fixture route |

The distinction is between an excluded input and a reachable uncontrolled
authority path. An empty listing alone proves neither. Authenticated modes
stay unqualified; they cannot silently enter a later live design. Conversely,
requiring account access to finish a deliberately credential-free proof would
change this investigation's scope rather than strengthen its evidence.

### Gate and next action

The acceptance packet was committed as `98e47a4` before any recovery code.
Independent read-only Codex review of the pinned source, existing artifact and
that packet found **no unresolved startup authority gap for this exact
credential-free candidate**. This satisfies Slice B's startup prerequisite
under the [frozen qualification plan](../plans/handoffs/M8-native-qualification-plan.md),
not production startup qualification. The following source/artifact chain is
part of that scoped conclusion, not an assumption that every feature is off:

- In the pinned `codex-rs/cloud-config/src/service.rs`,
  `load_startup_bundle` returns no bundle before cache or network access when
  authentication is absent. The private home is new, environment is cleared,
  and the observed account is null. Authenticated behavior remains expressly
  outside the accepted fixture's scope unless recipe safety depends on it;
  no such dependency was found here.
- `codex-rs/app-server/src/message_processor.rs` starts plugin tasks, and
  `codex-rs/core-plugins/src/manager.rs` permits anonymous curated sync.
  Plugins are enabled by default; startup can attempt Git before inventory.
  Its inputs are pinned code plus controller-owned empty/private paths, not
  a model-selected repository/configuration. Fixed external destinations have
  no route in this namespace. The only reachable peer is the bounded local
  fixture, whose script is controller-selected. This is physical exclusion
  of external startup input, not a plugin-disable or no-process claim.
- The full source tree's `shell_zsh_fork_skill_scripts_ignore_declared_permissions`
  is an upstream shell-tool test, not a separate baseline script executor.
  It dispatches `exec_command`; baseline `shell_tool=false` prevents that
  registration, and the native refused-call control checks the boundary.
- Artifact `10287620781` baseline files
  `codex-placement-230d45c1adcfaf9d.json` and
  `codex-placement-92e0cd706976b7b8.json` cover the two models. Both record
  `packaged_shell=false`, controller setup containing only the public marker,
  null account/requirements, two peer requests without peer failures, clean
  owner/payload exits, loopback alone and no IPv4 route. The placement proof
  supplies the namespace/socket boundary; these files do not independently
  establish all possible network or descendant-lifecycle claims.

The empty inventory is corroboration, not the reason for exclusion. Changing
the home, working directory, configured extensions, environment, network,
catalog or driver invalidates this conclusion and requires requalification.
Unexpected reachable behavior is a named blocker, not a reason to expand a
denylist or relabel a missing test as safe. Exact-head gates for this packet
and job-budget change are recorded in its linked PR before merge.

The now-unblocked, separately reviewed Slice B reuses ordinary SQLite capability leases,
`ControlPlane`/`RunHost`, acquisition closure, and the same Linux process owner
to prove native-home, protocol-resource, worker and checkpoint recovery across
real process death. It stays a separate reviewed change. A source review or a
portable fake cannot substitute for that new Linux proof.

Only a positive combined startup **and durable lifecycle** result supports a
proposed successor ADR. Its account/provider conformance and eventual operator
actions remain explicit; no credentials, billing, gateway deployment, live
adapter, new network/grant schema or additional owner is authorized here.
The existing gateway choice remains independent, not a substitute for the
owner's subscription-reuse goal.

### Durable fixture follow-up (PR #64)

The separately committed [acceptance and recovery record](../plans/handoffs/M8-native-recovery-evidence.md)
now carries executed SQLite/RunHost evidence from source head `8c8a3c7` and
[Linux run 34663385354](https://github.com/sushiHex/constructicon/actions/runs/34663385354),
artifact `10288154121`. Both pinned model profiles cover all five death seams;
cancellation and ownership transfer are separate cases. Checkpointed work
restores without another native call; uncheckpointed work uses a new acquisition.
The first failed ownership test and the artifact observer correction remain
explicit in the record. The linked PR owns final exact-head gates and independent
review, including the corrected exact-worker session observation.

| Qualification claim | Disposition |
| --- | --- |
| Bounded, account-empty startup and native/worker mediation | Scoped positive evidence in #62 and the combined native lane |
| Native acquisition, home/process lifetime, SQLite recovery and retained checkpoints | Executed positive evidence in #64; final corrected-head gates required before merge |
| An old revoked host performs durable disposal, or no artifact means no request | Refuted; successor owns cleanup and interrupted evidence is partial |
| Authenticated/cloud-managed startup, externally reachable extensions, real account/provider use | Unexecuted; the fixture's physical exclusions cannot qualify these modes |

After the final corrected-head proof, the next design artifact may be a
**proposed** successor to ADR 0018. It must name the changed trust clauses,
trusted code, strict profile/version compatibility, revocation/recovery and
new account/network/startup conformance gates. No existing profile can be
relabeled to supply those proofs. The task-shaped, provider-neutral seam
remains the extension point for later Codex, Claude Code, Pi, OpenRouter,
cloud and local adapters; this one native fixture does not qualify them.
No authentication route is selected or accepted here. #38 remains the owner
decision, and no credentials, provider calls, gateway deployment or paid API
substitute follow from this result.

## The contract does not need another abstraction

[ADR 0005](../adr/0005-executor-seam.md) already admits subscription CLIs and
cloud/local models through compatible task harnesses. Reuse `ExecutorProvider`,
`Executor`, invocation leases, declared grants, and truthful outcomes. Model
transport and authentication belong to the concrete adapter, not a provider
enum, a completion gateway implemented here, or a walker decision.

The owner's subscription-reuse goal is explicit. It does not erase
[accepted ADR 0018](../adr/0018-live-executors-are-leased-contained-processes.md):
initial account credentials and gateway bearer secrets stay outside the whole
untrusted CLI boundary; only a revocable invocation route enters it. PR B's
networkless launcher grants no authentication authority.

## What the published interfaces establish

- **Codex:** ChatGPT sign-in provides subscription access; API-key usage is
  billed separately. The CLI normally retains login state in its credential
  store. Ephemeral storage changes persistence, not what the running process
  possesses. The official CI recommendation is API-key authentication.
  [Authentication](https://learn.chatgpt.com/docs/auth).
- **Codex app-server:** experimental external-token authentication lets a host
  manage refresh, but supplies an access token to app-server. This is not a
  documented credential-free subscription route into our untrusted child.
  [App-server authentication](https://learn.chatgpt.com/docs/app-server).
- **Claude Code:** Anthropic distinguishes an end user signing into its
  unmodified binary with their subscription from a developer collecting or
  intermediating Claude.ai credentials. Hosted native-binary use has stated
  conditions; it is not blanket permission for a third-party OAuth broker.
  A permissive integration library cannot override the provider's terms.
  [Legal and credential-use guidance](https://code.claude.com/docs/en/legal-and-compliance).
- **Claude apps gateway:** the documented upstreams are API/cloud providers,
  not a Pro/Max subscription conversion service. Its SSO bearer and deployment
  model do not by themselves satisfy our per-acquisition revocation contract.
  [Gateway documentation](https://code.claude.com/docs/en/claude-apps-gateway).
- **Pi:** its task harness supports process/RPC integration, custom providers,
  and local models. That is evidence for adapter extensibility, not evidence
  that every advertised subscription route is authorized or satisfies M8.
  [Upstream harness documentation](https://github.com/badlogic/pi-mono/tree/main/packages/coding-agent).

These are current published interfaces, not compatibility proofs for the exact
CLI builds eventually admitted. Provider policy and technical containment are
separate gates. This record interprets their architectural consequences; it
does not adjudicate an account's legal eligibility.

## Result and recommendation

No documented, tested subscription route has yet been established that meets
the accepted whole-CLI credential boundary. Do not implement a home-grown
OAuth relay, copy desktop login files into CI, silently switch to paid API
usage, or describe lack of evidence as a provider-wide prohibition.

Keep the accepted gateway-only mode in force and keep subscription adapters
unavailable until their route is proved. Safe capture and contained gates can
proceed independently; neither needs credentials or a live model.

Before PR E, bring the owner an explicit choice:

1. Select an API/cloud-backed gateway deployment and its separate billing,
   then prove its invocation-route contract. This follows ADR 0018 but does
   **not** fulfill subscription reuse.
2. Pursue a successor design for native subscription use. The candidate worth
   testing is a trusted, unmodified native harness owning its own login, with
   every model-selected tool confined behind our existing lease boundary.
   This is a hypothesis, not an approved implementation: first establish that
   the pinned CLI offers complete tool mediation without host built-ins,
   arbitrary extensions, credential reads, or an alternate execution path.
   An incomplete mediation interface makes that adapter unavailable.

The second option changes the trust boundary and requires an accepted
successor ADR naming precisely what it supersedes. It must preserve READ/WRITE
containment, revocation, exact identity, restart cleanup, and the single
task-shaped seam. Native harness authentication must use the vendor's own
supported flow. No security downgrade is authorized by this record.

The owner authorized investigating option 2. The
[native-authentication investigation](../plans/handoffs/M8-native-auth-feasibility.md)
records current CLI interfaces, a pinned Hardline comparison, and a local
Codex protocol-schema probe. Complete mediation is not established: dynamic
tool dispatch is not proof of exclusive dispatch, and Claude's `canUseTool`
callback is not a universal interceptor. No credential-bearing integration
was attempted, and no successor ADR is accepted by that investigation.

The next proposed experiment was a credential-free, pinned Codex app-server
driver/worker probe, followed separately by native CLI integration against a
supported offline test interface if one existed. Its results follow below;
scripted peers alone cannot
qualify the native CLI. This keeps the subscription goal explicit without
inventing a broker abstraction or spending on a different billing route.
Credentials, paid calls, and live deployment remain separate operator actions.

## Linux experiment follow-up (2026-09-10)

The [pinned native mediation experiment](../plans/handoffs/M8-native-mediation-probe.md)
establishes a supported credential-free custom-provider path and a real dynamic
callback into the existing contained worker. It does not establish exclusive
mediation. The earlier/image-enabled configuration exposes a native reader
that exports the PNG fixture without a worker callback; the tested
`features.view_image = false` configuration removes that tool and refuses its
direct invocation. The contained-worker callback succeeds in both cases.
Model-dependent tool inventories, startup/extensions, client-RPC reachability
and lifecycle ownership remain unqualified, not that tested disabled-image
path. The accepted trust boundary remains unchanged. No authentication
deployment or billing choice is inferred from authorization to run this test.

Before live implementation, issue #38 still needs the owner's concrete route
decision. A separately billed gateway must be selected and proved as deployed;
a native successor needs positive combined mediation and lifecycle evidence.
The [OpenRouter assessment](OPENROUTER.md) proposes reuse of the planned Pi
executor, not another authentication route or completion API in the kernel.

## Bounded decision packet (PR #49)

The follow-up uses the same pinned `0.153.4` Linux binary, but selects its
bundled `gpt-5.5` and `gpt-5.6-sol` model metadata rather than relying on an
unknown model's fallback. No model was contacted: a credential-free loopback
fixture supplies every response. These model names identify the measured
configuration, not an account's entitlement or a recommended billing choice.

The assessed recipe fails complete mediation for both real model profiles.
With images disabled and `apply_patch_freeform = false`, a native patch call
still writes a harmless fixture in the disposable harness home without a
contained-worker callback. Sol also publishes CodeMode and collaboration
surfaces despite the requested false feature flags. A recognized configuration
field is not proof of effective disablement. The
[evidence matrix](../plans/handoffs/M8-native-mediation-probe.md#bounded-follow-up-pr-49)
separates those observations from controls that work and surfaces not proved.

This is sufficient to reject **this recipe as a credential-owning harness**;
it is not evidence that every possible supported native configuration fails.
Do not author a successor ADR as if its prerequisite had passed. Startup and
lifecycle spot checks cannot cancel a demonstrated unmediated write, and
additional feature switches alone are not a design proof.

Issue #38 is now a concrete owner decision, not permission to keep widening
this experiment indefinitely:

- **Keep subscription reuse as the goal:** authorize a separately bounded
  investigation of a specifically identified, supported complete-mediation
  interface or different native recipe. State how it closes the native patch
  path, model-dependent surfaces and startup/lifecycle obligations before
  implementation. No trusted-harness ADR or live adapter is qualified yet.
- **Choose a gateway instead:** name the deployment and accept its separate
  API/cloud billing, then prove the existing invocation-route contract there.
  This stays within ADR 0018 but does not fulfill subscription reuse.
- **Defer live adapters:** retain the completed fake-first containment work
  and leave E-H unavailable until a viable route is chosen.

Recommendation: preserve the subscription goal and the existing trust boundary;
do not substitute a paid route or promote this failing recipe. Further native
work needs a concrete new interface/configuration hypothesis and authorization,
not another broker, a weakened boundary, or credentials in the lab. None of
these owner choices has been made by this packet. #38 and its dependent work
remain open; closure of an investigation cannot unlock live implementation.

## Controlled catalog follow-up (PR #50)

The owner authorized the specific startup-catalog experiment, not a new
authentication route. The same pinned binary now refuses native patch calls
for both selected real model profiles when their patch selector is absent.
An unchanged-catalog control still writes the fixture. Sol also honors the
direct-tool selection and loses its CodeMode/collaboration surface while
retaining the contained callback. The
[evidence record](../plans/handoffs/M8-native-mediation-probe.md#controlled-catalog-experiment-pr-50)
names exact catalog bytes and preserves the model-specific wire inventories.

This advances the subscription-first hypothesis without authorizing credentials.
Literal driver-death probes additionally observe stopped native execution and
a stopped contained worker, followed by explicit provider reconciliation and
a fresh native invocation. Acquisitions do not dispose themselves on death;
the recovery calls cause their closure. The rows are serialized fixtures, not
RunHost's journal recovery, and native-home/all-descendant ownership is not
proved. Existing B/C/D recovery remains evidence for those resources only.

Next qualification must close those lifecycle and startup/configuration gaps
before proposing a successor ADR. The narrow catalog result is not complete
mediation, a production launch identity, or permission to place a reusable
secret in the harness. ADR 0018 remains the accepted boundary. No API billing
substitution, Pi qualification, or OpenRouter readiness follows from this work.

## Qualification prerequisite (PR #51)

The [bounded qualification plan](../plans/handoffs/M8-native-qualification-plan.md)
records an established interface blocker: the current Linux launcher feeds
one complete stdin buffer and closes it. The native app-server instead needs
requests that depend on earlier replies and worker results. Concurrent output
draining does not provide that duplex interface. This follows directly from
`LinuxLauncher._run` at the PR #50 merge, `8a2da8de653b919e492558eafb921d973e7535eb`;
it is source evidence, not a newly executed native lifecycle proof.

Before lifecycle qualification, a separately reviewed and authorized bounded
duplex contract must preserve the existing supervisor and acquisition owner.
Startup observations alone cannot resolve that prerequisite. Neither a
second process manager nor a recorded-executor test can substitute for the
missing native composition. No native qualification code or successor ADR is
claimed by PR #51; [#38](https://github.com/sushiHex/constructicon/issues/38)
remains the decision point.

## Controlled startup and provider placement (PR #54)

The transport prerequisite is merged in PR #52/#53 at
`6d6379c56bc1dd44a6f32f82b00efefbefdbe939`. It preserves the existing owner;
it does not supply a network route. The
[controlled-startup evidence](../plans/handoffs/M8-controlled-startup-evidence.md)
records native startup in a separate immutable test image through that duplex
interface. Config/session and inert skill controls have scoped observations;
managed/cloud/profile/plugin and full startup authority remain unqualified.

The provider experiment is negative: the existing external fake HTTP endpoint
is unreachable under the unchanged network namespace. Native startup and turn
creation succeed, but network retry continues until the owned deadline, not
until a terminal native turn. The record preserves this distinction and the
native warnings. A failed exchange is not positive model mediation.

The next decision is a separately reviewed supported credential-free fixture
arrangement, with its exact network boundary and one lifetime owner stated
before implementation. This is not permission to move the CLI outside the
boundary, deploy a gateway, use an account, or substitute paid calls. Startup
completeness and the provider prerequisite still gate native journal recovery;
ADR 0018 and authentication unavailability remain unchanged.

## Accepted test-only provider fixture

PR #54 is squash-merged as `e5e0dd7b65210ee882bb38ab371b6a4f97c1e2d5`,
tree-identical to its reviewed head. Its bounded negative result stands.
The [provider-fixture proposal](../plans/handoffs/M8-provider-fixture-proposal.md)
keeps the scripted provider in the trusted test driver and proposes one
test-only Unix socket mount plus a byte bridge inside the existing owned
namespace. It states the added peer reachability rather than claiming the
unchanged networkless recipe, and publishes no production executor profile.

The owner accepted the exact reviewed proposal at `35946af` on 2026-09-11;
PR #55 merged it as `7d1e56c`. Its historical proposed wording remains frozen.
Acceptance authorizes the placement-proof implementation only, recorded in the
[placement evidence](../plans/handoffs/M8-provider-placement-evidence.md).
The proposal separates placement proof from combined startup/mediation proof;
native durable recovery follows neither automatically. No credentials,
gateway deployment, billing choice or successor ADR is accepted here.
