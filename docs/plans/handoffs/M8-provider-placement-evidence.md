# M8 provider placement evidence

Status: test-only placement instrument. Exact-head gate results and current
review disposition belong to [PR #56](https://github.com/sushiHex/constructicon/pull/56),
not to the historical proposal's status line.

The owner explicitly approved the [fixture proposal](M8-provider-fixture-proposal.md)
at reviewed head `35946aff2eb07661ad1d2522f29d752756f3e815` on 2026-09-11.
[PR #55](https://github.com/sushiHex/constructicon/pull/55) squash-merged as
`7d1e56c1c8dcbdd37e7a3d01dd988d281baff847`, with the same tree. The proposal's
bytes remain frozen; its pre-decision wording is historical, not an outstanding
acceptance gate for this slice.

## Scope and evidence limits

Only placement is authorized here: one test-only Unix socket leaf mount and a
private-loopback byte bridge under the existing owner, with a bounded fake
Responses peer in the test driver. No production launcher interface, profile,
network schema, AppArmor change, credentials, paid request, or second supervisor.

An external peer records invocation bytes, not authenticated CLI authorship.
The supervisor reports the direct payload exit, not a bridge return code. Loss
after delivery of all required bytes may be invisible; successful native output
cannot manufacture the missing bridge observation. Host bounds must hold for
direct socket callers independently of the bridge.

Combined startup/mediation proof is a separate slice. Native durable recovery
and authentication remain gated by the qualification plan and ADR 0018.

## Observations and retained failed hypothesis

The first Linux run, on `69fee9c`, reached the scripted peer from the pinned
native CLI: one request, no peer failure, direct payload and supervisor exits
both zero, no timeout or capture bound. Its downloaded artifact shows only
loopback, no IPv4 routes, the named immutable/private/device mounts and socket
leaf, and only standard descriptors at bootstrap entry. This is placement,
not combined mediation or native durable recovery.

That run had 59 passing placement/peer/recipe checks, two inapplicable transport
skips, and one failed assertion. The escaped descendant deliberately ignored
TERM: the native payload reported 143 while the outer supervisor reported 137
after grace. Equating those two facts was wrong. The timeout control now checks
native TERM separately from the supervisor's TERM/KILL teardown race, alongside
the deadline, capture bound, and birth-pinned descendant/reaping proof. It does
not turn either result into a successful invocation.

- [Initial Linux run](https://github.com/sushiHex/constructicon/actions/runs/34640107306)
- [Downloaded artifact](https://github.com/sushiHex/constructicon/actions/runs/34640107306/artifacts/10279358887)

## Review corrections and proof boundary

Independent reviews found and prompted these corrections:

- The host peer drains after half-closing its response, so trailing/pipelined
  requests cannot disappear. Malformed content lengths refuse before conversion.
- A failed bind cannot unlink someone else's pathname; a replaced endpoint is
  reported and left untouched. Repeated cancellation joins every handler through
  the existing `finish_owned` helper.
- Preflight requires the observed pinned mount inventory and flags, not a path
  prefix. Endpoint identity remains the checked device/inode pair, not a
  shadowing filesystem dictionary. Entry and post-setup descriptor facts are
  recorded separately; the bridge proves its own inherited descriptor set.
- Scenario validation checks the exact controlled user prompt before a reply.
  This is not authentication of the sender or validation of all native startup
  instructions; those remain explicitly separate questions.
- Mid-request loss now occurs after forwarding a chunk of a larger request;
  peer byte consumption and incomplete framing must both witness it. Loss after
  final response delivery remains the documented unobserved-exit control.
- Failed conversations retain setup and complete available process outcomes;
  the case emits evidence only after peer handlers join, including on exceptions.
  The older TCP lane also checks and serializes its final peer state after join.

The source includes native reachability, mount mismatch, absent host/sibling and
other-invocation endpoints, malformed/oversized traffic, readiness and forwarding
loss, cancellation, deadline, controller death, and session-changing descendant
controls. Portable assertion mutants cover the shared limits, framing, scenario,
recipe, mount predicates, and evidence preservation. Each control's observations
are narrower than production availability. Consult the PR's exact-head Linux,
repository, mutation, review, and downloaded-artifact results before merging;
the earlier outer-lab lane cannot substitute for placement evidence.
