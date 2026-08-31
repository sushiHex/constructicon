"""The canonical human-in-the-loop exchange contracts (M7, channel schema 1).

Defined once here in L0 so the control plane and the standard components cannot
drift apart: an approval reached through `runs_approve` and one reached through
`constructicon.std/human-approval` are the same exchange, typed by the same pair
of nominal contracts, or they are not the same exchange at all.

That matters because a request-bound approval writes an `ApprovalRecord` — a
governance fact — into a channel exchange. Nominal typing is what keeps it from
being written into an arbitrary approval-interaction conversation that merely
looks similar.

**A payload is caller-authored; authorship is not.** `Channel.ask` hands a
component the reply's payload and nothing else, deliberately: widening it would
put the whole message inside every component's reach. So anything a component is
allowed to *promise* about authority has to be written into the payload by the
executor, from authenticated and stored facts, rather than accepted from
whoever answered. Both payload laws below are built here, from those facts, and
called by the executor — never assembled by a caller.
"""

from __future__ import annotations

from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from constructicon.core.channel import (
    ChannelContract,
    ChannelInteraction,
    ChannelMessage,
)
from constructicon.core.effect import ApprovalRecord
from constructicon.core.identity import Digest, JsonValue

ADVICE_REQUEST_CONTRACT = ChannelContract(
    type_id="constructicon.std/AdviceRequest",
    schema_hash="advice-request-1",
)
ADVICE_REPLY_CONTRACT = ChannelContract(
    type_id="constructicon.std/AdviceResponse",
    schema_hash="advice-response-1",
)
APPROVAL_REQUEST_CONTRACT = ChannelContract(
    type_id="constructicon.std/ApprovalRequest",
    schema_hash="approval-request-1",
)
APPROVAL_REPLY_CONTRACT = ChannelContract(
    type_id="constructicon.std/ApprovalDecision",
    schema_hash="approval-decision-1",
)


CANONICAL_EXCHANGES: tuple[tuple[ChannelContract, ChannelContract, ChannelInteraction], ...] = (
    (ADVICE_REQUEST_CONTRACT, ADVICE_REPLY_CONTRACT, "advice"),
    (APPROVAL_REQUEST_CONTRACT, APPROVAL_REPLY_CONTRACT, "approval"),
)


def canonical_exchange_fault(
    request: ChannelContract,
    reply: ChannelContract,
    interaction: ChannelInteraction,
) -> str | None:
    """Why this compiled exchange is not a coherent canonical human exchange.

    The contracts say what crosses; the endpoint says under whose authority. For
    these two exchanges those are not independent facts, and admission is the
    only place that sees both.

    An approval exchange sealed as advice is answered by `channels_reply`, which
    stamps only advice replies — so a human holding `constructicon:advise` alone
    would author the entire `ApprovalRecord`, actor and decision included, that
    the run then returns as a trusted governance fact. An advice exchange sealed
    as approval is the mirror: `channels_reply` refuses the interaction and
    `runs_approve` refuses the contracts, so the run parks with nothing able to
    answer it.

    Recognized by either half, because a pair naming one canonical contract and
    not its partner is not a canonical exchange half-dressed — it is a mismatch,
    and sealing it would be the same error one step further on.
    """

    for canonical_request, canonical_reply, required in CANONICAL_EXCHANGES:
        if request != canonical_request and reply != canonical_reply:
            continue
        if request != canonical_request or reply != canonical_reply:
            return (
                f"pairs {request.type_id!r} with {reply.type_id!r}; the canonical "
                f"{required} exchange pairs {canonical_request.type_id!r} with "
                f"{canonical_reply.type_id!r}"
            )
        if interaction != required:
            return (
                f"is the canonical {required} exchange, so its endpoint must seal "
                f"interaction={required!r}, not {interaction!r} — otherwise the "
                "authority that answers it is not the authority it describes"
            )
    return None


class _HumanPayload(BaseModel):
    """A payload that crosses a channel and comes back from durable storage.

    Deliberately not ``strict``: these are validated out of stored JSON, where a
    payload arrives as plain Python objects rather than as the models that
    produced it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class ApprovalRequestPayload(_HumanPayload):
    """What a human is being asked to approve.

    ``subject`` is carried as plain JSON rather than a typed ``ProofSubject``
    because its only job here is to be compared, and comparison is a bytes law:
    ``1 == True`` and ``1 == 1.0`` are Python facts, not JSON ones, so a typed
    field invites the model equality that would accept a decision about a
    subject this request never pinned.
    """

    schema_version: Literal[1] = 1
    subject: JsonValue


class ApprovalDecisionPayload(_HumanPayload):
    """The one answer an approval request admits: the trusted record itself.

    Carrying the whole `ApprovalRecord` rather than a bare decision is what lets
    the standard component return a governance fact instead of a rumour. The
    record names its own approval id, subject, authenticated actor, run, and
    time, so a component can parse it, compare its subject against the one it
    asked about, and hand back something an auditor can follow — all without
    seeing anything but the payload.

    Approved and rejected are ordinary data inside it. Nothing branches on which
    it is; both are one decision, recorded and woken identically.
    """

    schema_version: Literal[1] = 1
    approval: ApprovalRecord


class AdviceReplyPayload(_HumanPayload):
    """One advisor's answer, carrying the authorship the executor observed.

    ``advice`` is what the human wrote. ``actor_id`` and ``message_id`` are not:
    they are stamped from the authenticated command and the derived reply
    identity. Without that, a component returning "who advised" would be
    repeating a claim the payload made about itself.

    ``message_id`` is carried rather than recomputed so the reply identity law
    stays in one place — a component that re-derived it would be a second
    implementation of it.
    """

    schema_version: Literal[1] = 1
    advice: JsonValue
    actor_id: str
    message_id: Digest


def approval_decision_payload(approval: ApprovalRecord) -> JsonValue:
    """The reply an approval request admits, derived from the stored record.

    Derived rather than passed, so the answer a run reads and the governance
    fact an auditor reads can never disagree about what was decided, by whom.
    """

    return cast(
        JsonValue,
        ApprovalDecisionPayload(approval=approval).model_dump(mode="json"),
    )


def sealed_reply_payload(
    request: ChannelMessage,
    *,
    answer: JsonValue,
    actor_id: str,
    reply_id: Digest,
) -> JsonValue:
    """The payload a reply stores, as the request's sealed contract requires it.

    Only the canonical advice exchange is stamped, because only its reply
    contract promises authorship. Every other advice channel stores exactly what
    its answerer wrote: the request's sealed reply contract decides what a reply
    is, here as everywhere else, rather than the executor deciding for it.
    """

    if request.reply_contract != ADVICE_REPLY_CONTRACT:
        return answer
    return cast(
        JsonValue,
        AdviceReplyPayload(
            advice=answer,
            actor_id=actor_id,
            message_id=reply_id,
        ).model_dump(mode="json"),
    )
