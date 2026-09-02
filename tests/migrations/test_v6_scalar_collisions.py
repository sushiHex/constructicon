"""A schema-6 acknowledgement scalar is a token, not a reference.

That era let any caller choose the string, and every later command derives its
identity from its own actor, operation, and key — so a scalar can come to equal
a command that has nothing to do with the exchange it sits beside. Two readers
resolved the string anyway. The batched wake attached the colliding command to
the acknowledgement and held it to a law it never took part in; the reply
projector looked an approval up under it and, finding one minted for something
else, condemned the store. Neither is what happened to the history.
"""

from __future__ import annotations

from pathlib import Path

from constructicon.core.channel import ChannelMessage, message_for_reply
from constructicon.core.control import (
    OPERATE_SCOPE,
    AuthenticatedActor,
    CommandClaim,
    approval_id_for_command,
    command_id_for,
    command_request_hash,
)
from constructicon.core.effect import ApprovalRecord
from constructicon.core.human import ApprovalPlan, StoredApprovalPlan
from constructicon.core.identity import JsonValue, json_value
from constructicon.substrate.journal._sqlite_channels import _insert_message
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.channel_requests import AttestedMailboxChannel as MailboxChannel
from tests.conftest import FakeClock
from tests.migrations.test_sqlite_v6_to_v7 import (
    ADVISOR,
    APPROVER,
    CHANNEL_ID,
    RUN,
    SUBJECT,
    _approval_intent,
    _downgrade_v7_schema_to_v6,
    _intent,
)

ADVISOR_ACTOR = AuthenticatedActor(
    actor_id=ADVISOR,
    auth_method="static",
    scopes=frozenset({OPERATE_SCOPE}),
)


def _seed_legacy_reply(
    database: Path,
    clock: FakeClock,
    *,
    approval: bool,
    scalar: str,
) -> ChannelMessage:
    """One schema-6 request, reply, and acknowledgement under a chosen scalar."""

    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = channel.append_request(
        _approval_intent() if approval else _intent(),
        "att-v6-collision",
    )
    actor_id = APPROVER.actor_id if approval else ADVISOR
    reply = message_for_reply(
        request,
        actor_id=actor_id,
        payload={"answer": "ship"},
        created_at=clock.now(),
    )
    with journal._txn() as connection:
        _insert_message(connection, reply, None, scalar)
        connection.execute(
            "INSERT INTO channel_acks (message_id, actor_id, command_id, acked_at,"
            " ack_provenance_version) VALUES (?, ?, ?, ?, NULL)",
            (str(request.message_id), actor_id, scalar, clock.now().isoformat()),
        )
    _downgrade_v7_schema_to_v6(database)
    return request


def _claimed(
    journal: SqliteJournal,
    actor: AuthenticatedActor,
    operation: str,
    key: str,
    request: JsonValue | None = None,
) -> CommandClaim:
    if request is None:
        request = {"key": key}
    result = journal.claim_command(
        actor=actor,
        operation=operation,
        idempotency_key=key,
        request_hash=command_request_hash(request),
        request=request,
        owner_id="test:collision",
        ttl_s=30,
    )
    assert result.claim is not None
    return result.claim


def test_the_batched_wake_does_not_attach_a_colliding_command_to_a_v6_ack(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """Batching changes the query's shape, never its evidentiary strength."""

    database = tmp_path / "v6-ack-collision.db"
    scalar = command_id_for(ADVISOR, "runs_cancel", "collide")
    request = _seed_legacy_reply(database, clock, approval=False, scalar=scalar)

    migrated = SqliteJournal(database, now_fn=clock.now)
    exact = MailboxChannel(migrated, channel_id=CHANNEL_ID).reply_for(request.message_id)
    assert exact is not None
    assert migrated.answered_requests([request.message_id]) == {
        request.message_id: exact.message_id
    }

    # Now a real command comes to share the string.
    _claimed(migrated, ADVISOR_ACTOR, "runs_cancel", "collide")

    assert MailboxChannel(migrated, channel_id=CHANNEL_ID).reply_for(request.message_id) == exact
    assert migrated.answered_requests([request.message_id]) == {
        request.message_id: exact.message_id
    }
    SqliteJournal(database, now_fn=clock.now)


def test_a_later_unrelated_approval_does_not_reclassify_a_v6_reply(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """An approval is this reply's only if its plan names this exchange."""

    database = tmp_path / "v6-approval-collision.db"
    scalar = command_id_for(APPROVER.actor_id, "runs_approve", "later")
    request = _seed_legacy_reply(database, clock, approval=True, scalar=scalar)

    migrated = SqliteJournal(database, now_fn=clock.now)
    exact = MailboxChannel(migrated, channel_id=CHANNEL_ID).reply_for(request.message_id)
    assert exact is not None

    # A standalone decision, minted later under exactly that string, about
    # nothing to do with this request.
    subject = json_value(SUBJECT.model_dump(mode="json"))
    claim = _claimed(
        migrated,
        APPROVER,
        "runs_approve",
        "later",
        request={
            "run_id": str(RUN),
            "subject": subject,
            "decision": "approved",
            "reason": None,
        },
    )
    assert claim.command_id == scalar
    record = ApprovalRecord(
        approval_id=approval_id_for_command(claim.command_id, subject),
        subject=SUBJECT,
        decision="approved",
        reason=None,
        actor=APPROVER,
        run_id=RUN,
        created_at=clock.now(),
    )
    migrated.store_command_plan(
        claim,
        StoredApprovalPlan(plan=ApprovalPlan(approval=record)).model_dump(mode="json"),
    )
    migrated.store_approval(claim, record)
    migrated.complete_command(claim, {"approval_id": record.approval_id})

    assert MailboxChannel(migrated, channel_id=CHANNEL_ID).reply_for(request.message_id) == exact
    assert migrated.answered_requests([request.message_id]) == {
        request.message_id: exact.message_id
    }
    SqliteJournal(database, now_fn=clock.now)
