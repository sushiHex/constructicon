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
authentication, and complete live executor profiles. PR A contracts and PR B
networkless Linux containment are merged; deployed gateway conformance and
native model adapters remain outstanding. Operator deployment is separate
from GitHub Actions proof runs.

Accepted [ADR 0019](0019-hosted-linux-runners-are-requalified-not-image-pinned.md)
records the owner's GitHub Actions selection and the explicit adjustment from
an immutable hosted image to per-host qualification. It supersedes only M8
rev 1's CI-host-image requirement; the original plan and ADR 0018 keep their
historical bytes and all other proof obligations remain governing. The
[qualification workflow](../M8_CI.md) investigates prerequisites only; the
separate required native lane establishes PR B's containment evidence. Neither
enables a credential-bearing live executor. The
[native-authentication investigation](../plans/handoffs/M8-native-auth-feasibility.md)
changes no accepted ADR and records the additional proof a successor would need.

Proposed [ADR 0020](0020-native-harnesses-mediate-contained-tools.md) and
[M8 rev 2](../plans/milestones/M8-live-executors-rev2.md) now present that
successor for decision after the credential-free startup and recovery gates.
They propose vendor-managed account custody in a workspace-free native zone,
separate contained tool workers, versioned authority, and Codex-first sequencing.
They do not accept native authentication or replace the governing ADRs above;
account access, production conformance and live calls remain separate gates.
