# M8 provider placement evidence

Status: implementation in progress; no placement proof claimed yet.

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

## Verification

Not executed yet for this implementation: native Linux placement controls,
independent review, exact-head CI, assertion mutants, and artifact inspection.
The earlier startup/mediation lanes are baselines, not evidence for this fixture.
