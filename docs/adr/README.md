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

Proposed [ADR 0018](0018-live-executors-are-leased-contained-processes.md)
and the [M8 review draft](../plans/milestones/M8-live-executors-rev1.md)
propose a Linux-first leased process boundary, explicit credential delegation,
and complete live executor profiles. They are not accepted decisions or
implemented guarantees.
