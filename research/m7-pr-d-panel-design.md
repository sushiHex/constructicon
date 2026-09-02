# M7 PR D — panel pattern: design record

Status: revised after adversarial review (Codex, twelve findings; ten
accepted, two narrowed), then implemented as written on branch `m7/pr-d-panel`.
Approved plan: rev 2 §4 ("unchanged from rev 1 §12"), §7 "Slice D must add".
This records the decisions the plan leaves open, the constraints the code
imposes, and what the review changed. The implementation record
(`docs/plans/handoffs/M7-implementation-record.md`, "PR D — the panel pattern")
is the durable summary; this is the working design it was built from.

## What the code fixes

- A graph input is in every node's binding pool (`_compile_graph`, validator
  :243), so one request fans out to N members with no connection.
- A `many` port gathers every compatible source in the node's pool nominally
  (`_bind_port` :917). That pool is the *transitive* upstream closure plus
  every graph input (:238, `_upstream_closure` :1093). A connected node whose
  output has another contract contributes nothing and is not missed. An
  explicit map names one `node.port` (:990) and a destination port takes one
  map (:1145), so a multi-source fan-in cannot be made exact by maps.
- A channel-bound component declares exactly one input and one output; that
  pair is the compiled exchange (`_compiled_channel` :743). Only the canonical
  advice reply is stamped with authorship (`sealed_reply_payload`), and the
  caller's whole answer sits under `advice` as data.
- The walker hands a `many` port a list of payloads in sealed source order and
  drops the source address (`_collect`, walker :1901). An implementation's
  output is accepted after a port-name and JSON check (:1633); nothing stamps
  provenance into a payload.
- A component knows `ctx.run_id` and `ctx.path`, nothing else about where it
  sits. Loop frames are `IterationFrame`s, not scope segments.
- Composite definitions carry `capability_requirements=None` and bind inside
  their Graph (registry :325, authoring :219); `()` means "declares none".
- Nothing in M7 owns time. A parked human blocks its dependents until a reply
  is observed (walker :541, ARCHITECTURE :341).

## Decisions

**D1 — `panel()` is literal Graph sugar over bundles.**
`panel(name, *members: DefinitionBundle, aggregator: DefinitionBundle,
ids=None, aggregator_id=None)` returns a `workflow` bundle whose body is:

    nodes       = [member_i ...] + [aggregator]
    connections = [Connection(src=member_i, dst=aggregator)]   # no maps
    inputs      = the members' one request port
                  + the aggregator's non-`many` inputs, in declared order
    outputs     = the aggregator's outputs

Members and the aggregator are bundles, never bare Refs: exactness is proved
at authoring from their declared contracts, which a name cannot supply.
Authoring refuses, with a typed error, unless: every member declares exactly
one input and one output and all members declare the same pair; the
aggregator declares exactly one `many` port and its contract is the members'
output contract; every other aggregator input is nominally distinct from that
contract (else it would magnetically bind a member); all boundary port names
are unique. Node ids follow `flow`'s derivation, and the aggregator's id is
its component's last segment unless `aggregator_id` says otherwise.

Byte equality (§7) is to the golden direct Graph in exactly this order — node,
connection, and port order participate in `source_graph_hash` and therefore
`manifest_hash`. Two semantically equivalent hand-authored Graphs are not
promised equal; canonicalising graph identity would be an IR decision.

The gather is exact for the shape `panel()` emits: no graph input carries the
result contract, no member's internal nodes leak (a composite exposes only its
declared outputs), and a same-level bystander is not upstream. A hand-authored
graph that adds a compatible input or a compatible helper upstream of a member
widens the gather; that is the general connector law, tested here as such.

**D2 — L0 contracts live in `core/panel.py`, nominal, strict.**

    PanelMemberOutcome = "responded" | "declined" | "unavailable" | "timed_out"
    PanelBallot        = "approve" | "reject" | "abstain"
    PanelMemberResult  { schema_version=1, run_id, member: ExecutionPath,
                         outcome, ballot | None, rationale: JsonValue | None,
                         actor_id: ActorId | None, message_id: Digest | None }
    PanelQuorum        { schema_version=1, required_approvals: PositiveInt }
    PanelTally         { approve, reject, abstain, declined, unavailable,
                         timed_out: NonNegativeInt }   # sums to member count
    PanelOutcome       = "approved" | "rejected" | "insufficient_responses"
                       | "impossible_quorum"
    PanelResult        { schema_version=1, outcome, quorum, tally,
                         members: tuple[PanelMemberSummary, ...] }
    PanelMemberSummary { node: str, result: PanelMemberResult }
    PanelBallotPayload { schema_version=1, outcome: "responded" | "declined",
                         ballot | None, rationale | None }   # extra="forbid"

`ballot` is present iff `outcome == "responded"`, model-validated. Every
outcome is explicit member data: M7 owns no clock, so `unavailable` and
`timed_out` are what a member or policy component *reports*, never what the
kernel infers from elapsed time. A real human who does not answer keeps the run
parked; one who will not answer replies `declined`.

**D3 — member identity is reported by the producer and checked for shape;
it is not kernel-attested.** A member stamps `member = ctx.path`, which is the
genuine path the walker gave it — but the payload is the member's to write,
and `_collect` drops the source address, so the aggregator cannot compare the
two. Kernel-attested identity for `many` ports would change the atomic
invocation contract and is deferred, recorded below.

What the aggregator does check is everything the kernel makes checkable. Let
`S` be the aggregator's own scope segments and `P = S[:-1]` its parent. Every
result's `member.scope.segments` must begin with `P` and have a segment at
index `len(P)`; that segment is the member's `node`. Duplicate exact member
paths and duplicate derived nodes are contract violations, so a member that
claims a sibling's identity collides with the sibling rather than replacing
it. Any other topology is refused: the derivation is defined for members that
are the aggregator's siblings, which is what `panel()` emits, and claims
nothing about arbitrary nesting. Members are ordered by the canonical JSON of
the complete `ExecutionPath`, never by `render()`, which is not injective.
(Implementation note: one exact path repeated is a node repeated, so a single
node-level duplicate check is the whole law; a separate path check was dead
code and a mutant proved it.)

For a human member, the stamp is written by the standard adapter (D5), which
is not the human's code; for a fake, by the fake, which is the author's code.

**D4 — the aggregator is a pure standard component,
`constructicon.std/panel-quorum`,** with `capability_requirements=()`.
Inputs `votes` (`many`, PANEL_MEMBER_RESULT) and `quorum` (one, PANEL_QUORUM);
output `result` (PANEL_RESULT). The outcome is total and says what happened:

    impossible_quorum       required_approvals > member count
    approved                approve >= required_approvals
    insufficient_responses  responded < required_approvals
    rejected                otherwise: enough answered, and they did not approve

Same members in any input order give the same bytes. Rev 2 waits for every
declared member, so the aggregator never sees a partial set.

**D5 — the human member is composition, not a new exchange.** A human panel
member is `human-advisor` (canonical advice pair, authorship stamped) followed
by `constructicon.std/panel-ballot`, an adapter with input `advice`
(ADVICE_REPLY) and output `vote` (PANEL_MEMBER_RESULT), declaring
`capability_requirements=()`. It parses the outer `AdviceReplyPayload`, then
its `advice` as a `PanelBallotPayload` — strict, so an `actor_id` a human
writes inside their answer is a malformed ballot, not a claim. `actor_id` and
`message_id` are copied from the outer stamped payload, so the vote carries
the transport's provenance and can be followed back to its durable reply;
`actor_id` is telemetry until a consumer does so. The composite is authored
per participant by `human_panel_member(name, channel_id)`, because each human
needs its own channel id carrying its own endpoint (rev 2 §4) and a Ref's
`bind` is per instance (validator :802); it must be registered and promoted
like any definition. Nothing enters `CANONICAL_EXCHANGES`; nothing new is
stamped.

**D6 — fake members are ordinary tasks** with input ADVICE_REQUEST and output
PANEL_MEMBER_RESULT, reporting any of the four outcomes as data with no
transport provenance. The credential-free acceptance lane: two fakes plus one
mailbox-backed human across a real process restart, the panel result adapted
into an `ApprovalRequestPayload`, and the existing approval lane across a
second restart.

## Failure proof (rev 2 §7, slice D)

- Byte equality to the golden direct Graph, and equal `manifest_hash`, for
  inferred and explicit ids and for repeated component names; typed refusal
  for members that cannot share one contract, an aggregator without exactly
  one matching `many` port, and a colliding boundary.
- A same-level bystander contributes nothing; a compatible graph input or a
  compatible helper upstream of a member does, and the test says so; a
  connected member of another contract is refused at authoring; a `one` port
  fed by two members raises the existing ambiguity fault.
- Every declared member appears exactly once by node, across shuffled input
  orders, for all four outcomes; duplicate paths, a foreign topology,
  impossible quorum, and all-absent are each refused or named.
- One advisor round trip and one approval round trip complete across real
  process restarts, credential-free, with one request, reply, ack, approval,
  and wake cause each.
- Mutation check (shipped): nine mutants — no canonical order, no sibling
  check, no duplicate check, no run check, both threshold off-by-ones, the
  ballot bucket, the member-binding check, the gather-contract check — each
  killed by `tests/core/test_panel.py` and `tests/sdk/test_combinators.py`.

## Deferred, recorded

- Kernel-attested identity on `many` ports (source address delivered with
  each value). Changes the atomic invocation contract; an IR/runtime decision.
- Wall-clock timeouts for human members. Needs a timer owner, a durable
  observation, and wake law; outside slice D.

## Rejected

- A panel-specific exchange with stamped authorship: widens
  `CANONICAL_EXCHANGES` and `sealed_reply_payload` for no gain.
- Member identity by `actor_id`: fakes have none; two members may share one.
- Inferring quorum from member count: the plan forbids hidden defaults.
- Calling every threshold miss "rejected": overstates what members said (I4).
