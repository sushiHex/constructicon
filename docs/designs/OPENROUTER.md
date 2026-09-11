# OpenRouter: reuse a task harness

Status: proposed integration scope, 2026-09-10. Tracks
[#47](https://github.com/sushiHex/constructicon/issues/47); not approved M8
scope, a qualified adapter, or authorization for account access or paid calls.

## Recommendation

Use the planned Pi executor with an explicit OpenRouter configuration. Do not
create an `OpenRouterExecutor` merely because the model endpoint changes.
OpenRouter supplies inference and routing; Pi supplies the task/tool loop.
Constructicon supplies the same admitted grants, acquisition lifetime,
containment, capture, gates, and task outcome used by other executors.

This is a source-grounded reuse candidate, not tested compatibility. The Pi
adapter itself is still unimplemented. A second concrete executor would need
a demonstrated harness incompatibility, not a provider-brand distinction.

## Evidence and limits

The pinned [Pi model configuration guide at `400d690`](https://github.com/earendil-works/pi/blob/400d6905ce46ec46e79da8a7701b1b48850192df/packages/coding-agent/docs/models.md)
documents custom endpoints, exact model entries and
`compat.openRouterRouting`. The latter carries OpenRouter's provider policy.
It also documents two traps: free-form `samplingParams` can override named
request fields, and disabling `supportsFinishReason` permits inferred stream
completion. Neither is suitable as an uncontrolled compatibility escape here.
No Pi process or model request was run for this assessment.

The pinned [request builder](https://github.com/earendil-works/pi/blob/400d6905ce46ec46e79da8a7701b1b48850192df/packages/ai/src/api/openai-completions.ts)
confirms that explicit routing is copied independently of base-URL detection,
then free-form sampling parameters are applied last. It also refuses missing
finish reasons when the corresponding support flag is true. These are source
observations; the future native tests must exercise their effective settings.

[OpenRouter's routing reference](https://openrouter.ai/docs/guides/routing/provider-selection),
inspected on 2026-09-10, exposes provider allowlists, fallback controls,
parameter-support requirements, and data-handling constraints. Defaults are
not Constructicon policy. An explicit provider order alone is not a closed
allowlist. These documented fields establish a configurable interface, not
proof of deployment enforcement or model compatibility.

`system.describe()` was exercised against a fresh credential-free assembly:
description schema 3, existing fake executor policy and Graph schema 1. The
existing [`ExecutorProvider` / `Executor`](../../src/constructicon/core/executor.py)
seam already carries task execution and content-bound launch identity. No
Graph, walker, public MCP, journal, or completion-provider API extension is
justified by this enhancement. See [ADR 0005](../adr/0005-executor-seam.md).

## Smallest initial scope

One pinned Pi build and transport, two explicitly selected and independently
qualified model configurations, and no automatic model or provider fallback.
Both configurations run the same registered task component. Capability
configuration selects the model; the graph never branches on the provider.

For each offered configuration:

- Bind the exact model id, finite admitted tool sets, explicit effort mapping,
  context/output bounds, schema support, and routing/data policy into the
  existing launch identity. Do not expose Pi's whole discovered catalog.
- Require an explicit closed upstream allowlist, disable fallback, and require
  support for all requested parameters. Data collection, retention and billing
  remain explicit operator choices. Refuse an unsatisfiable selection.
- Generate controlled Pi configuration: no arbitrary caller JSON, shell-backed
  credential/header values, project overrides, or parameter bags that can
  overwrite model, tools, route, streaming, or completion checks. Use Pi's
  native supported configuration; do not fork its inference loop.
- Verify that routing survives the invocation bridge's changed base URL. A
  harness's automatic endpoint recognition is not policy; an explicit override
  that the selected build ignores makes the configuration unavailable.
- Keep requested and observed model/provider separate. Unknown observation is
  absent, not copied from the request. Catalog cost estimates are not observed
  billing. A terminal Pi event alone cannot repair a damaged upstream stream;
  prove that the selected native protocol retains enough evidence to demote it.

## Authentication and authority

The accepted [ADR 0018](../adr/0018-live-executors-are-leased-contained-processes.md)
still governs this proposal: the whole Pi child is untrusted. A reusable
OpenRouter key stays outside it. The child receives only the invocation's
revocable route; a public placeholder may be used only when it has no
authority outside that route. Direct key injection or copying a desktop login
is not an alternative implementation of this design.

OpenRouter's public endpoint is not, by itself, the per-acquisition gateway
required by M8. A selected deployment must independently prove close-by-key,
expiry, revocation of existing streams, routing/auth enforcement, policy
identity and drift refusal. Model-selected code can author HTTP requests, so
host-side policy must enforce the admitted model/upstream restrictions; Pi's
generated request body alone cannot enforce them. Do not add policy to the
byte bridge or implement a general completion gateway in this repository.

[#38](https://github.com/sushiHex/constructicon/issues/38) owns the explicit
authentication/deployment decision. No deployment or billing route is chosen
by this assessment. A future native-subscription successor would not
automatically authorize an OpenRouter API key or qualify this integration.

## Evidence before availability

These are future gates, not results of this document:

1. Pin a concrete Pi build and prove its discovery, configuration precedence,
   tool inventory and native stream behavior in the existing Linux boundary.
2. Through a credential-free controlled upstream, capture the actual requests
   for two model selections. Assert exact model, tools, routing and output
   controls; attempt to overwrite each through configuration and task data.
3. Exercise truncation, missing terminal facts, malformed tool arguments,
   rate limits, timeout, cancellation, stream bounds and requested/observed
   identity mismatches. No inferred successful completion is acceptable.
4. Exercise the same task component and acquisition cleanup through
   ControlPlane/RunHost, including response loss, restart and simulated
   disposal. READ and WRITE each need their honest profile and physical proof.
5. Prove the selected gateway against controlled upstreams and its actual
   deployment policy. A fake proves the test contract, not the deployment.
6. Run the repository/native gates and independent exact-head review. A live
   smoke test, if desired, is a separately authorized operator action.

## Sequencing

Keep #47 open without `ready` or an M8 milestone assignment. The reuse proposal
is the bounded follow-on scope selected for review in
[PR #49](https://github.com/sushiHex/constructicon/pull/49): configure the
planned Pi adapter, qualify two explicit models independently, and permit no
automatic fallback. This selects a reuse direction, not a model pair, billing
route, deployed gateway, or implementation availability.

The Pi harness needs qualification under #42 and authentication still needs
the #38 decision before implementation can be promised. Do not reinterpret
the Codex native experiment as Pi or OpenRouter evidence. A future native
subscription design would not by itself qualify OpenRouter's API-key route.
The issue records these conditional prerequisites; no new unconditional
dependency or expansion of M8 is created by this review. Current work state
belongs to the issues, not a duplicate checklist here.
