"""Scratch probe — approve-only actor on a bound approval."""

from __future__ import annotations

import sqlite3

from constructicon.api.system import Constructicon
from constructicon.core.control import (
    APPROVE_SCOPE,
    AuthenticatedActor,
    command_id_for,
)
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_request_bound_approval import (
    ATTESTATION,
    RUN,
    SUBJECT,
    _gate,
    _intent,
)

APPROVE_ONLY = AuthenticatedActor(
    actor_id="static:approver",
    auth_method="static",
    scopes=frozenset({APPROVE_SCOPE}),
)


async def test_probe_approve_only(
    world: Constructicon,
    journal: SqliteJournal,
    tmp_path,
) -> None:
    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(), ATTESTATION)
    outcome: object
    try:
        outcome = await gate.control.runs_approve(
            APPROVE_ONLY,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason="ok",
            idempotency_key="probe-1",
            request_message_id=request.message_id,
        )
    except BaseException as exc:  # noqa: BLE001
        outcome = f"RAISED {type(exc).__name__}: {exc}"

    cid = command_id_for("static:approver", "runs_approve", "probe-1")
    record = journal.command(cid)
    reply = gate.channel.reply_for(request.message_id)
    raise AssertionError(
        f"outcome={outcome!r} state={record.state if record else None!r} "
        f"reply={reply is not None} launches={len(gate.host.launches)}"
    )
