# Architecture Decision Records

History by reference (I9): adjudication, alternatives, and calibrated
guarantees live here so the normative documents stay short. The planning
history behind these records is the v12+errata design review (12 rounds,
including two external reviews and a self-improvement addendum, adjudicated
decision by decision).

Current M6 control decisions are [ADR 0012](0012-durable-control-plane-and-mcp.md)
and [ADR 0013](0013-local-assembly-through-command-law.md). The current M7
channel decisions are [ADR 0014](0014-channel-identity-and-delivery.md), which
settles what a message is, and
[ADR 0015](0015-human-authority-on-channels.md), which settles who may read and
answer one. [ADR 0016](0016-positive-durable-facts-and-provenance-eras.md)
settles how immutable facts remain distinguishable from absence and how exact
historical writer eras retain only their original authority. Accepted
[ADR 0017](0017-panel-membership-is-an-authored-map.md) records the M7.1
decision that exact panel membership is an authored port map, not inferred
connector liveness.

Accepted [ADR 0018](0018-live-executors-are-leased-contained-processes.md)
and the [frozen M8 plan](../plans/milestones/M8-live-executors-rev1.md)
define a Linux-first leased process boundary, gateway-only initial
authentication, and complete live executor profiles. PR A is authorized;
physical containment and deployed gateway conformance remain unimplemented
proof gates, and operator provisioning requires a separately selected target.

Accepted [ADR 0019](0019-hosted-linux-runners-are-requalified-not-image-pinned.md)
records the owner's GitHub Actions selection and the explicit adjustment from
an immutable hosted image to per-host qualification. The
[qualification workflow](../M8_CI.md) investigates prerequisites only; it does
not establish PR B containment or enable a live executor.
