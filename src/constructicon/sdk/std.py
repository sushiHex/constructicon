"""The standard human-in-the-loop components (M7).

The two channel-bound ones are atomic and declare exactly one input, one
output, and one durable channel capability. Admission compiles that exchange
with nothing left to choose at call time. Both ask through the narrow
`ChannelFacade`, so neither receives routing or actor-selection authority and
all either sees of an answer is its payload.

The two panel components hold no capability at all and say so. `panel-ballot`
turns one human's advice reply into a panel vote carrying the authorship the
executor stamped; `panel-quorum` concludes a panel from every member's report
under an explicit quorum. A human panel member is the advisor and the ballot
composed — not a new exchange — which is what keeps authorship stamped and
`CANONICAL_EXCHANGES` unchanged.

Nothing here registers anything at import. A module that registered on import
would make importing it a mutation, and restart recovery imports it precisely
because it must *not* mutate: `ComponentRegistry` re-imports the module named by
a stored `PythonRef` and expects to find the same function it recorded.
`definitions()` returns the bundles; a launcher decides whether to register.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from constructicon.core.channel import MAILBOX_CHANNEL_KIND
from constructicon.core.component import (
    CapabilityRequirement,
    ComponentDef,
    PythonRef,
)
from constructicon.core.errors import ContractViolation
from constructicon.core.graph import Ref
from constructicon.core.human import (
    ADVICE_REPLY_CONTRACT,
    ADVICE_REQUEST_CONTRACT,
    APPROVAL_REPLY_CONTRACT,
    APPROVAL_REQUEST_CONTRACT,
    AdviceReplyPayload,
    ApprovalDecisionPayload,
    ApprovalRequestPayload,
)
from constructicon.core.identity import canonical_json, digest, json_value
from constructicon.core.panel import (
    PANEL_MEMBER_RESULT_CONTRACT,
    PANEL_QUORUM_CONTRACT,
    PANEL_RESULT_CONTRACT,
    PanelBallotPayload,
    PanelMemberResult,
    PanelQuorum,
    aggregate_panel,
)
from constructicon.core.ports import Port
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import source_digest_for
from constructicon.sdk.combinators import flow
from constructicon.sdk.types import DefinitionBundle

ADVISOR_COMPONENT = "constructicon.std/human-advisor"
APPROVAL_COMPONENT = "constructicon.std/human-approval"
PANEL_BALLOT_COMPONENT = "constructicon.std/panel-ballot"
PANEL_QUORUM_COMPONENT = "constructicon.std/panel-quorum"
ADVISOR_CHANNEL = "advisor"
APPROVAL_CHANNEL = "approver"
# A human waits across process death, so these require a durable transport by
# name. `channel.in_process` honestly declares `durability="process"`: a
# request parked on one would not survive the restart the human outlives.
DURABLE_CHANNEL_KIND = MAILBOX_CHANNEL_KIND


def _port(name: str, contract: Any) -> Port:
    """One port typed by a canonical contract, so the pair cannot drift."""

    return Port(name=name, type_id=contract.type_id, schema_hash=contract.schema_hash)


ADVICE_REQUEST = _port("request", ADVICE_REQUEST_CONTRACT)
ADVICE_REPLY = _port("advice", ADVICE_REPLY_CONTRACT)
APPROVAL_REQUEST = _port("request", APPROVAL_REQUEST_CONTRACT)
APPROVAL_DECISION = _port("decision", APPROVAL_REPLY_CONTRACT)
PANEL_VOTE = _port("vote", PANEL_MEMBER_RESULT_CONTRACT)
PANEL_VOTES = Port(
    name="votes",
    type_id=PANEL_MEMBER_RESULT_CONTRACT.type_id,
    schema_hash=PANEL_MEMBER_RESULT_CONTRACT.schema_hash,
    cardinality="many",
)
PANEL_QUORUM = _port("quorum", PANEL_QUORUM_CONTRACT)
PANEL_RESULT = _port("result", PANEL_RESULT_CONTRACT)


async def human_advisor(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    """Ask one human for advice and return it with the authorship it came with.

    The advice is the advisor's. `actor_id` and `message_id` are not: the
    executor stamped them from the authenticated command and the derived reply
    identity, so what this returns about *who* advised is a transport fact
    rather than a claim the answer made about itself.
    """

    answer = await ctx.channel(ADVISOR_CHANNEL).ask(inputs["request"])
    reply = AdviceReplyPayload.model_validate(answer)
    return {"advice": reply.model_dump(mode="json")}


async def human_approval(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    """Ask one human to approve a subject and return the trusted record.

    The reply carries the whole `ApprovalRecord`, so this can hand back a
    governance fact rather than a rumour about one. It still checks that the
    record decides the subject that was asked about: the transport already
    proved the reply belongs to this request, this run, and this path, but only
    the request itself knows what it asked.
    """

    request = ApprovalRequestPayload.model_validate(inputs["request"])
    answer = await ctx.channel(APPROVAL_CHANNEL).ask(request.model_dump(mode="json"))
    decision = ApprovalDecisionPayload.model_validate(answer)
    approval = decision.approval
    decided = json_value(approval.subject.model_dump(mode="json"))
    if canonical_json(decided) != canonical_json(json_value(request.subject)):
        # A bytes law, not model equality: `1 == True` and `1 == 1.0` are Python
        # facts, and a decision about a different subject is not this decision.
        raise ContractViolation(
            f"approval {approval.approval_id} decides a subject this request did not ask about"
        )
    if approval.run_id != ctx.run_id:
        # The transport proved the reply belongs to this run; the record inside
        # it is separate data and must say so too, or this run would return a
        # governance fact about another one.
        raise ContractViolation(
            f"approval {approval.approval_id} records run {approval.run_id!r}, not {ctx.run_id!r}"
        )
    return {"decision": decision.model_dump(mode="json")}


async def panel_ballot(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    """Turn one human's advice reply into a panel vote, with its provenance.

    The outer payload is the executor's: `actor_id` and `message_id` were
    stamped from the authenticated command and the derived reply identity, and
    they travel with the vote so it can be followed back to its durable reply.
    The inner `advice` is the human's, and it is read strictly as a ballot: a
    field the ballot does not know — an `actor_id` written inside the answer,
    say — is not a claim this component repeats, it is a malformed ballot, and
    a malformed ballot fails the run rather than becoming a vote (I4).

    `member` is this component's own path, which the walker handed it. Its
    parent is the member node the panel declared.
    """

    reply = AdviceReplyPayload.model_validate(inputs["advice"])
    try:
        ballot = PanelBallotPayload.model_validate(reply.advice)
    except ValidationError as exc:
        raise ContractViolation(
            f"advice reply {reply.message_id} from {reply.actor_id!r} is not a panel ballot"
        ) from exc
    vote = PanelMemberResult(
        run_id=ctx.run_id,
        member=ctx.path,
        outcome=ballot.outcome,
        ballot=ballot.ballot,
        rationale=ballot.rationale,
        actor_id=reply.actor_id,
        message_id=reply.message_id,
    )
    return {"vote": vote.model_dump(mode="json")}


async def panel_quorum(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    """Conclude a panel from every member's report under an explicit quorum.

    Pure: the same members in any order give the same bytes, and the outcome
    is the one law in `core.panel`. This component's own scope is what places
    the members — they are its siblings by `panel()` construction — so the
    aggregation derives each member's node from its reported path against that
    scope and refuses any other topology rather than guessing.
    """

    votes = tuple(PanelMemberResult.model_validate(vote) for vote in inputs["votes"])
    quorum = PanelQuorum.model_validate(inputs["quorum"])
    result = aggregate_panel(
        votes,
        quorum,
        aggregator_scope=ctx.path.scope.segments,
        run_id=ctx.run_id,
    )
    return {"result": result.model_dump(mode="json")}


def human_panel_member(name: str, channel_id: str) -> DefinitionBundle:
    """One human as a panel member: the advisor, then the ballot, composed.

    Authored per participant because each human needs their own channel id
    carrying their own sealed endpoint — `recipient_actor_id` does not
    participate in the request id, so two humans on one channel would collide —
    and a Ref's bindings are its own. It is a composite like any other: it must
    be registered and promoted, it carries no implementation, and it binds its
    channel inside its Graph rather than declaring one outside it.
    """

    return flow(
        name,
        Ref(component=ADVISOR_COMPONENT, bind={ADVISOR_CHANNEL: channel_id}),
        Ref(component=PANEL_BALLOT_COMPONENT),
        ids=("advisor", "ballot"),
        inputs=(ADVICE_REQUEST,),
        outputs=(PANEL_VOTE,),
    )


def _pure_definition(
    name: str,
    inputs: tuple[Port, ...],
    outputs: tuple[Port, ...],
    impl: Any,
) -> ComponentDef:
    """A complete contract that holds no capability, and declares that.

    `()` is not the same as omitting the field: omitted means capability-opaque
    history, `()` means "asked for nothing", and admission refuses to hand an
    empty declaration anything (I3).
    """

    return ComponentDef(
        name=name,
        role="node",
        capability_requirements=(),
        body=PythonRef(
            package="constructicon",
            module=impl.__module__,
            qualname=impl.__qualname__,
            contract_hash=digest(
                "component-contract",
                1,
                {
                    "inputs": [port.model_dump(mode="json") for port in inputs],
                    "outputs": [port.model_dump(mode="json") for port in outputs],
                },
            ),
            source_digest=source_digest_for(impl),
        ),
        inputs=inputs,
        outputs=outputs,
    )


def _definition(name: str, request: Port, reply: Port, alias: str, impl: Any) -> ComponentDef:
    """One complete contract: its ports, and the one capability it may hold.

    `capability_requirements` is declared rather than omitted. Omitting it means
    *capability-opaque* — the historical shape — and admission then validates no
    alias, no kind, and no extra binding, so a graph could hand these components
    any capability it liked. A component introduced today declares what it needs
    and, by doing so, refuses everything it does not (I3).
    """

    return ComponentDef(
        name=name,
        role="node",
        capability_requirements=(CapabilityRequirement(alias=alias, kind=MAILBOX_CHANNEL_KIND),),
        body=PythonRef(
            package="constructicon",
            module=impl.__module__,
            qualname=impl.__qualname__,
            contract_hash=digest(
                "component-contract",
                1,
                {
                    "inputs": [request.model_dump(mode="json")],
                    "outputs": [reply.model_dump(mode="json")],
                },
            ),
            source_digest=source_digest_for(impl),
        ),
        inputs=(request,),
        outputs=(reply,),
    )


def definitions() -> tuple[DefinitionBundle, ...]:
    """The standard components, canonical and ready to register — never registered.

    Returned rather than installed, so importing this module stays a read.
    """

    return (
        DefinitionBundle(
            definition=_definition(
                ADVISOR_COMPONENT,
                ADVICE_REQUEST,
                ADVICE_REPLY,
                ADVISOR_CHANNEL,
                human_advisor,
            ),
            implementation=human_advisor,
        ),
        DefinitionBundle(
            definition=_definition(
                APPROVAL_COMPONENT,
                APPROVAL_REQUEST,
                APPROVAL_DECISION,
                APPROVAL_CHANNEL,
                human_approval,
            ),
            implementation=human_approval,
        ),
        DefinitionBundle(
            definition=_pure_definition(
                PANEL_BALLOT_COMPONENT,
                (ADVICE_REPLY,),
                (PANEL_VOTE,),
                panel_ballot,
            ),
            implementation=panel_ballot,
        ),
        DefinitionBundle(
            definition=_pure_definition(
                PANEL_QUORUM_COMPONENT,
                (PANEL_VOTES, PANEL_QUORUM),
                (PANEL_RESULT,),
                panel_quorum,
            ),
            implementation=panel_quorum,
        ),
    )


__all__ = [
    "ADVISOR_CHANNEL",
    "ADVISOR_COMPONENT",
    "APPROVAL_CHANNEL",
    "APPROVAL_COMPONENT",
    "DURABLE_CHANNEL_KIND",
    "PANEL_BALLOT_COMPONENT",
    "PANEL_QUORUM_COMPONENT",
    "definitions",
    "human_advisor",
    "human_approval",
    "human_panel_member",
    "panel_ballot",
    "panel_quorum",
]
