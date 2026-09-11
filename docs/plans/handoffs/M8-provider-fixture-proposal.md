# M8 provider fixture: one endpoint, one process owner

Status: proposed; design review and explicit owner acceptance gate
implementation. This is a credential-free test arrangement, not a production
route, authentication decision, or successor to ADR 0018.

Base: `e5e0dd7b65210ee882bb38ab371b6a4f97c1e2d5`, squash merge of PR #54,
tree-identical to reviewed `ceda6f44fa1bfd44a829b44dd261e06ffb2150d5`.
[#37](https://github.com/sushiHex/constructicon/issues/37) owns investigation;
[#38](https://github.com/sushiHex/constructicon/issues/38) owns authentication.
This proposal changes neither issue's acceptance into a live-availability claim.

## Problem and proposed choice

The [startup evidence](M8-controlled-startup-evidence.md) proves a bounded
negative result: the native CLI starts inside `LinuxLauncher.exchange`, but
the existing fake HTTP listener is outside its fresh network namespace. Native
connection errors continue until the owner deadline. PR #50's working outer
lab provider does not qualify this different placement.

Keep the scripted provider in the trusted test driver. Expose exactly one
fresh filesystem Unix socket through an explicitly test-only, read-only leaf
mount. Inside the existing PID/network namespace, a small byte bridge connects
private loopback to that fixed socket. The existing bootstrap starts the bridge
and then replaces itself with the pinned CLI. The existing supervisor remains
the sole owner of every native and bridge process.

```text
trusted test driver
  existing Wire over ProcessIO ---------> native CLI
  bounded scripted Responses peer <---+     |
                                      |     | private loopback HTTP
  fresh Unix socket (only mounted leaf)+-- byte bridge
                                            |
                         CLI and bridge share the existing owned namespace
```

The peer does not forward requests, possess credentials, resolve upstream
hosts, or implement a provider service. It returns the same two scripted
Responses exchanges used by the existing test. Host-side request observations
stay outside the payload's writable files, output stream, and process domain.

## Authority and evidence limits

[INVARIANTS](../../INVARIANTS.md), [ADR 0018](../../adr/0018-live-executors-are-leased-contained-processes.md),
and the [qualification plan](M8-native-qualification-plan.md) remain unchanged.
ADR 0018 already describes a private-loopback bridge and acquisition-specific
socket for a future proved gateway. That is a useful placement, not permission
to call this fixture a gateway or borrow its unimplemented conformance.

This proposal explicitly adds **one reachable test peer**. It is not the
unchanged networkless startup experiment, and it must not be described as
fulfilling `network="none"`: ADR 0018 excludes model networking under that grant.
No `ExecutorProfile`, `ProviderRouteIdentity`, admitted capability, or new
grant/network enum is published. This directly exercised test composition
supplies no production availability. No default production launch gains a
socket mount or a route.

Source observations, not yet execution of this proposal:

- `LinuxLauncher.argv` always creates a fresh network namespace and exposes
  only its immutable root, private storage, and optional workspace. It has no
  provider-mount interface. `_supervisor.supervise_namespace` owns the direct
  payload and terminates/reaps its descendants when that payload exits.
- The pinned CLI's
  [provider model](https://github.com/openai/codex/blob/3d2ee51ca2d5db578f328aa75e20aa22c0197c9a/codex-rs/model-provider-info/src/lib.rs)
  supports an HTTP `base_url`, Responses, and no required OpenAI auth. PR #50
  exercised that combination without an Authorization header. No supported
  direct provider-over-Unix-socket control is established here; app-server
  Unix transport is a different interface.
- Upstream bubblewrap
  [v0.9.0 source](https://github.com/containers/bubblewrap/blob/v0.9.0/bubblewrap.c)
  invokes `loopback_setup()` for `--unshare-net`. The installed package is
  `0.9.0-1ubuntu0.1`, pinned by its executable digest. Upstream source alone
  does not prove the packaged binary's effective interfaces/routes; the native
  preflight below must observe them. No interface or route setup is added.
- The existing launch AppArmor profile permits networking; namespace and mount
  placement enforce isolation. No profile change is proposed.

Current [official configuration guidance](https://learn.chatgpt.com/docs/config-file/config-advanced)
is orientation only. Keep Codex `0.153.4`, source
`3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`, and the existing restricted catalog
for `gpt-5.5` and `gpt-5.6-sol`. No release bump or undocumented transport knob
is part of the experiment.

## Minimal implementation contract, after acceptance

### Fixture placement and identity

Use one test-private launcher composition over `LinuxLauncher`. Its command
construction calls the existing recipe and adds only the fixed socket-leaf
read-only mount before the command separator. It requires `workspace=None`;
do not disguise the endpoint directory as a workspace or mount its parent.
The immutable test image reserves `/opt/native-startup/provider.sock` as the
guest mountpoint. Both the inherited availability probe and the actual call
use the same composition; neither may obtain a broader recipe. Before native
exec, trusted setup observes the effective mount/network/FD facts of that
actual namespace, not only the earlier probe's separate namespace.
It may not remove or replace a namespace, clear-environment, capability-drop,
supervisor, guard, deadline, or capture argument. Test the exact argv delta.

The source socket lives in a fresh test-owned directory. Bind once before
launch, retain the listener and pathname unchanged until teardown, then remove
only that test's resource. No reconnection can select a different destination.
An absent, replaced, non-socket, or symlink endpoint refuses the fixture rather
than selecting a host address. The socket grants only access to scripted bytes;
a read-only mount does not make its protocol read-only.

The fixture has its own domain-separated launch identity, binding the existing
launch revision, exact composition source, fixed guest endpoint placement, and
new immutable runtime/bridge/bootstrap content. Do not inherit an unmodified
parent revision for overridden argv. Record actual ephemeral endpoint and
namespace observations separately from content identity; do not hash a host
path or nonce as architectural identity. Record each case's exact controlled
configuration and scenario bytes too. No production identity schema changes.
The controller alone selects those bytes, the endpoint and callback worker
bindings; model output cannot select any of them.

Reuse the current immutable-image builder, runtime inventory, pinned CLI
package, catalog projection, `DuplexWire`, guarded exchange helper and complete
`assert_outcome`. The image remains a test image with its own digest.

### Ownership and protocol

The bootstrap binds one ephemeral loopback listener before starting a single
fixed bridge child. That child inherits only its necessary listener and opens
the one mounted endpoint; it must not retain the CLI's stdin/stdout, guards,
or trusted supervisor descriptors. The bootstrap closes its copy of the
listener and `exec`s the CLI with the controlled loopback URL. This preserves
the direct payload identity whose exit the trusted supervisor reports. No
second controller, reaper, daemon, renewable timeout, or process-group cleanup
is introduced. A bridge failure cannot be treated as a completed native turn.

The bridge transports bytes to one fixed destination. It has bounded buffers,
connection count and byte totals, closes both halves on error, and carries no
model dispatch, URL routing, retry policy, or credential logic. The endpoint
refuses ancillary descriptor transfer; received descriptors are closed before
refusal. No descriptor crosses into the CLI or a model-selected callback.
The existing owner's absolute deadline bounds every child, including setup.

Extract and reuse the existing test provider's bounded request parsing and
scripted Responses generation for both TCP and Unix fixtures. Do not maintain
two provider laws or add a production provider abstraction. The fixture accepts
only its fixed request target, exact model/scenario, bounded native requests,
and no authentication header. Unexpected methods, framing, extra requests,
or malformed bodies fail the case. Requests are observations, never code for
the host to execute.

The peer is an async task in the existing test-driver process, not a new
physical process owner. Its context must join accepted handlers on every exit,
keep the socket mounted until launcher teardown finishes, and close/remove
the fixture afterward. OS closure on test-driver death is not journal recovery.
Record that distinction instead of inventing a durable fixture ledger.

## Proof slices and stop conditions

Acceptance authorizes a bounded test implementation, not all later M8 work.
Keep these as two reviewable changes; do not hide startup-origin completeness
inside a bridge patch.

1. **Placement proof.** Reproduce the old unreachable-peer control. With the
   proposed fixture, observe only private loopback, no external interfaces or
   routes, exact mount/FD topology and one reachable scripted endpoint. Prove
   host loopback services, socket siblings, authority/journal paths and another
   invocation's endpoint remain absent or unreachable. Fail preflight without
   native launch if the setup differs. Exercise endpoint loss, malformed and
   oversized requests, bridge failure, timeout, cancellation, owner death,
   and a session-changing descendant. Assert quiescence/reaping through the
   existing owner's proof, not a child's exit message or a PID's disappearance.
   Require complete native `ProcessResult` outcomes and host-side peer errors;
   a native success marker cannot erase either failure. No combined native
   mediation claim follows from reachability alone.
2. **Combined startup/mediation proof.** Run both pinned model profiles through
   this exact fixture. Preserve their distinct request-tool wire shapes.
   Exercise allowed callbacks and the existing patch/image/model-dependent
   refusal controls with live positive controls. Check host-observed requests,
   native RPC identities, callback results and complete process outcomes
   together. The controller dispatches any permitted worker through the
   existing contained-worker/acquisition path, never inside the provider or
   the native home. Do not credit a scripted callback as physical worker proof.
   Complete the origin/control/test inventory from PR #54: managed policy,
   named profiles, project TOML/trust, hooks, plugins/MCP/apps, packaged assets,
   environment and cloud/account absence. Use inert public markers and
   supported release controls. Account-authenticated behavior remains outside
   scope; if recipe safety depends on it, qualification stays blocked.

For either slice, require exact-head repository verification, Linux CI,
load-bearing assertion mutants, independent review, and separately inspected
downloaded artifacts. Retain failed hypotheses and identify what each positive
and negative control actually proves. Native wire data and fixture observations
are not governance attestations. The pre-existing outer-lab lane must still
pass, but cannot supply missing proof for this arrangement.

If this design requires additional production launcher parameters, a new
network/grant schema, host-policy relaxation, inherited authority descriptors,
credentials, a paid request, a second process owner, or unsupported native
controls, stop and bring that specific change back for decision. Do not append
an escape hatch to keep the experiment running. Endpoint-only communication
does not qualify future gateway isolation, billing, authentication or revocation.

Native SQLite/RunHost/home/revocation recovery remains the separate Slice B of
the qualification plan. It starts only after both proof slices establish a
supported startup recipe with no unresolved startup-authority gap. Successful
tests cannot accept a successor authentication ADR on the owner's behalf.

## Decision requested

Approve or redline this **test-only Unix endpoint mount and contained byte
bridge** arrangement. The material choice is introducing one explicit peer
across the test namespace, with the observations retained outside it. Review
approval and green CI are necessary evidence, not owner acceptance. Until that
acceptance is recorded, only this design PR proceeds; implementation is gated.

Alternatives considered:

- A fake provider beside the CLI inside the same writable/process domain is
  shorter, but its records can be affected by the native operations the test
  is meant to examine. It can demonstrate connectivity, not independently
  establish complete tool mediation.
- Moving the CLI back outside containment repeats the old experiment and loses
  the combined startup/ownership question.
- Sharing host networking or deploying a gateway widens this investigation
  and does not meet the credential-free, no-deployment decision requested.
- A new generic proxy, completion interface, or supervisor duplicates concepts
  instead of supplying the missing fixed test endpoint.
