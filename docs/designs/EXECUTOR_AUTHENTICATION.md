# Executor authentication: feasibility and next decision

Status: evidence and recommendation, 2026-09-09; not an accepted ADR or a
claim of working subscription integration. No login, credential inspection,
provider request, or gateway provisioning was performed.

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

The next proposed experiment is a credential-free, pinned Codex app-server
driver/worker probe, followed separately by native CLI integration against a
supported offline test interface if one exists. Scripted peers alone cannot
qualify the native CLI. This keeps the subscription goal explicit without
inventing a broker abstraction or spending on a different billing route.
Credentials, paid calls, and live deployment remain separate operator actions.
