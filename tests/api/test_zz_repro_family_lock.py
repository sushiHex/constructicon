"""Throwaway repro: approve-only / promote-only actors vs DetailResolver._family_lock."""

from __future__ import annotations

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.control import (
    APPROVE_SCOPE,
    AuthenticatedActor,
)
from constructicon.core.errors import JournalDamaged
from constructicon.substrate.journal.sqlite import SqliteJournal

from tests.api.test_request_bound_approval import (
    APPROVER_ID,
    ATTESTATION,
    RUN,
    SUBJECT,
    _gate,
    _intent,
)

APPROVE_ONLY = AuthenticatedActor(
    actor_id=APPROVER_ID,
    auth_method="static",
    scopes=frozenset({APPROVE_SCOPE}),
)


async def test_approve_only_actor_bound_decision(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(), ATTESTATION)

    with pytest.raises(JournalDamaged) as excinfo:
        await gate.control.runs_approve(
            APPROVE_ONLY,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason="looks right",
            idempotency_key="approve-only-1",
            request_message_id=request.message_id,
        )
    print("\nRAISED:", excinfo.value)

    reply = gate.channel.reply_for(request.message_id)
    print("REPLY COMMITTED:", reply is not None and reply.message_id)
    delivery = gate.journal.channel_delivery(
        message_id=request.message_id, actor_id=APPROVER_ID
    )
    print("REQUEST ACKED:", delivery is not None and delivery.acknowledged)
    print("RUN LAUNCHES:", gate.host.launches)

    # Retry with the same idempotency key: what does the operator see now?
    try:
        again = await gate.control.runs_approve(
            APPROVE_ONLY,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason="looks right",
            idempotency_key="approve-only-1",
            request_message_id=request.message_id,
        )
        print("RETRY:", type(again), again)
    except Exception as exc:  # noqa: BLE001
        print("RETRY RAISED:", type(exc).__name__, exc)
