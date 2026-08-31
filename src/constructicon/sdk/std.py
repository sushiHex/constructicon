"""The two standard human-in-the-loop components (M7).

Each is atomic, declares exactly one input and one output — which is what lets
admission compile its channel exchange with nothing left to choose at call time
— and holds no authority of its own. Both ask through the narrow
`ChannelFacade`, so all either one ever sees of an answer is its payload.

Nothing here registers anything at import. A module that registered on import
would make importing it a mutation, and restart recovery imports it precisely
because it must *not* mutate: `ComponentRegistry` re-imports the module named by
a stored `PythonRef` and expects to find the same function it recorded.
`definitions()` returns the bundles; a launcher decides whether to register.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from constructicon.core.component import ComponentDef, PythonRef
from constructicon.core.errors import ContractViolation
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
from constructicon.core.ports import Port
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import source_digest_for
from constructicon.sdk.types import DefinitionBundle

ADVISOR_COMPONENT = "constructicon.std/human-advisor"
APPROVAL_COMPONENT = "constructicon.std/human-approval"
ADVISOR_CHANNEL = "advisor"
APPROVAL_CHANNEL = "approver"


def _port(name: str, contract: Any) -> Port:
    """One port typed by a canonical contract, so the pair cannot drift."""

    return Port(name=name, type_id=contract.type_id, schema_hash=contract.schema_hash)


ADVICE_REQUEST = _port("request", ADVICE_REQUEST_CONTRACT)
ADVICE_REPLY = _port("advice", ADVICE_REPLY_CONTRACT)
APPROVAL_REQUEST = _port("request", APPROVAL_REQUEST_CONTRACT)
APPROVAL_DECISION = _port("decision", APPROVAL_REPLY_CONTRACT)


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
    decided = json_value(decision.approval.subject.model_dump(mode="json"))
    if canonical_json(decided) != canonical_json(json_value(request.subject)):
        # A bytes law, not model equality: `1 == True` and `1 == 1.0` are Python
        # facts, and a decision about a different subject is not this decision.
        raise ContractViolation(
            f"approval {decision.approval.approval_id} decides a subject this "
            "request did not ask about"
        )
    return {"decision": decision.model_dump(mode="json")}


def _definition(name: str, request: Port, reply: Port, impl: Any) -> ComponentDef:
    return ComponentDef(
        name=name,
        role="node",
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
                human_advisor,
            ),
            implementation=human_advisor,
        ),
        DefinitionBundle(
            definition=_definition(
                APPROVAL_COMPONENT,
                APPROVAL_REQUEST,
                APPROVAL_DECISION,
                human_approval,
            ),
            implementation=human_approval,
        ),
    )


__all__ = [
    "ADVISOR_CHANNEL",
    "ADVISOR_COMPONENT",
    "APPROVAL_CHANNEL",
    "APPROVAL_COMPONENT",
    "definitions",
    "human_advisor",
    "human_approval",
]
