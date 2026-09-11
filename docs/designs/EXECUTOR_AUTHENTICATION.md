# Executor authentication: feasibility and next decision

Status: evidence and recommendation, updated 2026-09-11; not an accepted ADR or a
claim of working subscription integration. No login, credential inspection,
remote provider request, or gateway provisioning was performed.

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
