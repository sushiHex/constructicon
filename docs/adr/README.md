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
define a Linux-first leased process boundary, complete live executor
profiles, and gateway-only initial authentication for the v1 profile. PR A–D
are merged; no live model adapter exists. Accepted ADR 0021 supersedes the
authentication clauses for the explicit v3 profile only; gateway v1 is
unchanged and unselected. Operator deployment is separate from GitHub
Actions proof runs.

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
[M8 rev 2](../plans/milestones/M8-live-executors-rev2.md) presented a
principal-attested successor for decision after the credential-free startup
and recovery gates: vendor-managed account custody in a workspace-free native
zone, separate contained tool workers, versioned authority, and Codex-first
sequencing. They remain proposed, neither accepted nor rejected, after ADR
0021 was accepted as the narrower alternative; ADR 0020's proposed
description-4 allocation is retired in favour of ADR 0021's, and its text is
unchanged. Account access, production conformance and live calls remain
separate gates.

Accepted [ADR 0021](0021-subscription-executors-bind-operator-stores.md)
(2026-09-13) and [M8 rev 3](../plans/milestones/M8-live-executors-rev3.md)
select the owner's immediate Claude Code/Codex subscription route: one private
operator binding, with vendor principal/workspace continuity explicitly
unverified, under unchanged physical containment, mediated tools, grants and
lifecycle proofs. It supersedes ADR 0018 only for the explicit v3 profile.
Acceptance authorizes credential-free N1 construction; N4 and N5 need
separate explicit operator authorization per provider, the private Linux
deployment is a separate operator decision, and no credential, account
inspection, model call or live profile is authorized. ADR 0019 still governs
hosted Linux evidence.
