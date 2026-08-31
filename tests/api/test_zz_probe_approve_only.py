"""Probe: an approver holding only constructicon:approve."""

from __future__ import annotations

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.control import (
    APPROVE_SCOPE,
    ApprovalCommandResult,
    AuthenticatedActor,
    ControlRejected,
)
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


async def test_standalone_approve_only(world: Constructicon, journal: SqliteJournal) -> None:
    gate = _gate(world, journal)
    result = await gate.control.runs_approve(
        APPROVE_ONLY,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="probe-standalone",
    )
    print("STANDALONE RESULT:", type(result).__name__, result)
    assert isinstance(result, (ApprovalCommandResult, ControlRejected))


async def test_bound_approve_only(world: Constructicon, journal: SqliteJournal) -> None:
    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(port="probe"), ATTESTATION)
    result = await gate.control.runs_approve(
        APPROVE_ONLY,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="probe-bound",
        request_message_id=request.message_id,
    )
    print("BOUND RESULT:", type(result).__name__, result)
    assert isinstance(result, (ApprovalCommandResult, ControlRejected))
