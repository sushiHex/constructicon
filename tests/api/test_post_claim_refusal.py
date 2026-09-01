"""A refusal decided after the claim is an outcome, not damage.

Some things a command must refuse cannot be known before it exists: they are
properties of the decision rather than of the request, so the claim is already
written when the answer turns out to be no. The durable command law has a place
for that — the command becomes terminal in state ``rejected``, carrying the
refusal as its stored response, and every later retry of the same idempotency
key replays exactly that answer.

What must never happen is the third outcome: a claimed command that can neither
commit nor refuse. Its key is spent, its row stays ``prepared`` forever, and
every retry raises `JournalDamaged` against a store that holds nothing wrong.
"""

from __future__ import annotations

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.control import ControlCode, ControlRejected, command_id_for
from constructicon.core.human import decoded_human_command_plan
from constructicon.core.identity import Digest
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_request_bound_approval import (
    APPROVER,
    APPROVER_ID,
    ATTESTATION,
    RUN,
    SUBJECT,
    _gate,
    _intent,
)


async def _refused(
    world: Constructicon,
    journal: SqliteJournal,
    *,
    run_id: RunId,
    decision: str,
    idempotency_key: str,
    request_message_id: Digest | None = None,
) -> ControlRejected:
    gate = _gate(world, journal)
    result = await gate.control.runs_approve(
        APPROVER,
        run_id=run_id,
        subject=SUBJECT,
        decision=decision,
        reason=None,
        idempotency_key=idempotency_key,
        request_message_id=request_message_id,
    )
    assert isinstance(result, ControlRejected), result
    return result


@pytest.mark.parametrize(
    ("decision", "run_id", "code", "key"),
    [
        ("maybe", RUN, ControlCode.APPROVAL_INVALID_SUBJECT, "post-claim-decision"),
        ("approved", RunId("run-absent"), ControlCode.RUN_UNKNOWN, "post-claim-run"),
    ],
)
async def test_a_post_claim_refusal_is_terminal_and_replays(
    decision: str,
    run_id: RunId,
    code: ControlCode,
    key: str,
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """The claim it already spent becomes the record of the refusal."""

    refused = await _refused(
        world,
        journal,
        run_id=run_id,
        decision=decision,
        idempotency_key=key,
    )
    assert refused.faults[0].code is code

    record = journal.command(command_id_for(APPROVER_ID, "runs_approve", key))
    assert record is not None
    assert record.state == "rejected", (
        f"the refused command is {record.state!r}; a spent key with no terminal "
        "outcome is a command nobody can ever finish"
    )

    # The plan records why nothing was written, so it names no domain fact.
    assert decoded_human_command_plan(record) is None

    replayed = await _refused(
        world,
        journal,
        run_id=run_id,
        decision=decision,
        idempotency_key=key,
    )
    assert replayed == refused


async def test_a_bound_decision_refused_after_its_claim_leaves_the_request_open(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """Refusing writes nothing, so the request is still there to be answered."""

    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(), ATTESTATION)

    refused = await _refused(
        world,
        journal,
        run_id=RUN,
        decision="maybe",
        idempotency_key="bound-post-claim",
        request_message_id=request.message_id,
    )
    assert refused.faults[0].code is ControlCode.APPROVAL_INVALID_SUBJECT
    assert gate.channel.reply_for(request.message_id) is None

    # A different key carrying a decision the plane accepts still answers it.
    answered = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="bound-post-claim-retry",
        request_message_id=request.message_id,
    )
    assert not isinstance(answered, ControlRejected), answered
    assert gate.channel.reply_for(request.message_id) is not None
