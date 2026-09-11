# M8 combined startup and mediation evidence

Status: acceptance checklist committed before implementation; not qualified.
Owner-authorized investigation: [issue #57](https://github.com/sushiHex/constructicon/issues/57).
Branch: `investigate/m8-combined-startup`.
Base: `6a5c2e43cfa1bda7f281a66886946668f471c5c7` (merged placement PR #56).

## Authority and bounds

This is the combined slice of the accepted
[provider fixture proposal](M8-provider-fixture-proposal.md), following its
[placement proof](M8-provider-placement-evidence.md) and the
[native qualification plan](M8-native-qualification-plan.md). It does not amend
those frozen documents. Existing startup observations remain in the
[startup evidence](M8-controlled-startup-evidence.md).

Reuse the exact test-only placement launcher, one bounded fake peer, byte bridge,
duplex conversation, acquisition guard, and existing process supervisor. Keep
the binary, model/catalog, runtime base, and bubblewrap pins. No new production
interface, supervisor, broker, ledger, schema, credential, live provider route,
authentication decision, host-policy relaxation, or durable native recovery.

## Acceptance checklist

These are future gates, not executed results. Both pinned profiles (`gpt-5.5`
and `gpt-5.6-sol`) must be observed inside the placement fixture.

1. Inventory each startup origin and its supported control. For managed/system,
   user/profile, project/trust, hooks, skills, plugins, MCP/apps, packaged assets,
   environment, and cloud/account state, distinguish physical absence, a positive
   discovery/execution control, a refusal, and an unqualified surface. A default
   empty listing is not proof that the corresponding source is disabled.
2. Define the provider-request assertion before interpreting native observations.
   Controller-authored turns have exact controlled content and sequence. Native
   context is a different field of evidence, with its expected shape and allowed
   variation stated explicitly. Do not learn an arbitrary first request as its
   own reference, authenticate origin by matching text, or silently ignore extra
   conversation turns. Unexpected context is a refused/unqualified observation,
   not permission to widen an allowlist until a positive case passes.
3. Link each allowed native callback to the actual contained worker invocation,
   its output, the returned native tool result, and the completed turn. Bind the
   peer transcript, native RPC/call identities, complete owned `ProcessResult`,
   and post-join peer failures in each record. Preserve both models' distinct
   request/tool wire shapes; `turn/completed` alone is insufficient. Exercise
   patch, image, and model-dependent refusal controls, including positive controls
   that prove a removed tool was reachable before its supported restriction.
   Preserve the worker's existing READ boundary and single physical owner.
4. Exercise a contained descendant/direct-socket request. The endpoint establishes
   invocation membership, not CLI authorship. Preserve this limitation even if a
   descendant can reproduce the exact permitted request; do not call matching
   bytes a process-authentication proof.
5. Test the assertion laws independently with malformed and substituted input,
   including earlier user content followed by the correct final prompt. Kill
   targeted assertion mutants. Preserve placement cleanup/failure controls and
   exact-head local, CI, native, and independent review gates. Audit downloaded
   artifacts, not only test counts, and record failed hypotheses as well as proofs.

## Native-context contract

The placement-only peer checks the final controlled prompt; its historical
acceptance did not validate earlier native context. The combined investigation
must not inherit a stronger claim from that check. Its expected context must be
grounded independently in the pinned release and controlled startup recipe.
Generated identifiers/time fields are observations, not caller authority; any
normalization must name the fields it excludes and why. Tool outputs are bound
to their call identifiers and observed worker results, not accepted as another
free-form user turn.

The fake peer remains a fixed response script chosen by the test controller.
Incoming context never selects executable fixture behavior. A deterministic
request check is a test assertion, not a new provider protocol or authorization
boundary. Unsupported context/state ends the relevant proof as partial/blocked.

## Stop conditions and handoff

A supported-control gap is a legitimate result. If an origin cannot be controlled
without changing the accepted boundary, record its exact reproduction and leave
qualification incomplete. Do not compensate with a second tool-name denylist,
new production restrictions, or borrowed desktop/account credentials.

Native journal/RunHost/home/revocation recovery remains gated on a supported
startup and mediation recipe. Completion here does not accept subscription auth.
Report proved, refuted-by-reproduction, unexecuted, and blocked-by-prerequisite
rows separately to issue #57 and the decision packet in issue #38. An overall
partial result must retain those distinctions. Keep the resulting implementation
PR draft for owner review.

## Executed evidence

None in this record yet. The checklist is intentionally committed first.
