"""The canonical human-in-the-loop exchange contracts (M7, channel schema 1).

Defined once here in L0 so the control plane and the standard components cannot
drift apart: an approval reached through `runs_approve` and one reached through
`constructicon.std/human-approval` are the same exchange, typed by the same pair
of nominal contracts, or they are not the same exchange at all.

That matters because a request-bound approval writes an `ApprovalRecord` — a
governance fact — into a channel exchange. Nominal typing is what keeps it from
being written into an arbitrary approval-interaction conversation that merely
looks similar.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from constructicon.core.channel import ChannelContract
from constructicon.core.identity import JsonValue

APPROVAL_REQUEST_CONTRACT = ChannelContract(
    type_id="constructicon.std/ApprovalRequest",
    schema_hash="approval-request-1",
)
APPROVAL_REPLY_CONTRACT = ChannelContract(
    type_id="constructicon.std/ApprovalDecision",
    schema_hash="approval-decision-1",
)


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
    """The one answer an approval request admits.

    Approved and rejected are ordinary data. Nothing downstream branches on
    which it is — both are one decision, recorded and woken identically.
    """

    schema_version: Literal[1] = 1
    decision: Literal["approved", "rejected"]
    reason: str | None = None
