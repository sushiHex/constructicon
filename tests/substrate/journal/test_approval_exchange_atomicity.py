"""Request-bound approval is one transaction, including on reconciliation."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.channel_commands import ack_command_id, ack_with_command
from tests.channel_requests import AttestedMailboxChannel as MailboxChannel
from tests.conftest import FakeClock
from tests.durable_seals import reseal_primary_fact
from tests.substrate.channels.test_channel_contract import (
    ATTESTATION,
    CHANNEL_ID,
)
from tests.substrate.channels.test_channel_contract import (
    _intent as _advice_intent,
)
from tests.substrate.journal.test_control_store import (
    ACTOR,
    APPROVAL_REQUEST,
    _approval,
    _claim,
)

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.channel import (
    ChannelAck,
    ChannelAckRecord,
    ChannelMessage,
    ChannelSendIntent,
    reply_message_id,
    request_message_id,
)
from constructicon.core.control import CommandClaim
from constructicon.core.effect import ApprovalRecord
from constructicon.core.errors import JournalDamaged
from constructicon.core.human import (
    APPROVAL_REPLY_CONTRACT,
    APPROVAL_REQUEST_CONTRACT,
    ApprovalPlan,
    ApprovalRequestPayload,
    ChannelApprovalPlan,
    StoredApprovalPlan,
    approval_decision_payload,
)
from constructicon.core.identity import Digest, JsonValue, canonical_json, json_value
from constructicon.substrate.journal._sqlite_approvals import (
    _APPROVAL_FACT_FAMILY,
    approval_fact_hash,
    seal_approval,
)
from constructicon.substrate.journal._sqlite_channels import (
    CHANNEL_ACK_FACT_FAMILY,
    CHANNEL_MESSAGE_FACT_FAMILY,
    _channel_ack_fact_key,
    channel_ack_fact_hash,
    channel_message_fact_hash,
    reply_in_transaction,
)
from constructicon.substrate.journal._sqlite_fact_seals import (
    sealed_fact_hash,
    store_durable_fact_seal,
)
from constructicon.substrate.journal.sqlite import SqliteJournal


def _approval_intent(approval: ApprovalRecord) -> ChannelSendIntent:
    path = ExecutionPath(scope=ScopePath(segments=("approval",)))
    return ChannelSendIntent(
        message_id=request_message_id(
            run_id=approval.run_id,
            path=path,
            channel_id=CHANNEL_ID,
            channel_revision="1",
            lane="approval",
            interaction="approval",
            port="request",
        ),
        channel_id=CHANNEL_ID,
        channel_revision="1",
        lane="approval",
        interaction="approval",
        recipient_actor_id=ACTOR.actor_id,
        contract=APPROVAL_REQUEST_CONTRACT,
        reply_contract=APPROVAL_REPLY_CONTRACT,
        run_id=approval.run_id,
        path=path,
        port="request",
        reply_port="decision",
        payload=ApprovalRequestPayload(
            subject=json_value(approval.subject.model_dump(mode="json")),
        ).model_dump(mode="json"),
    )


def _canonical_request_id() -> Digest:
    return request_message_id(
        run_id=RunId("run-control-contract"),
        path=ExecutionPath(scope=ScopePath(segments=("approval",))),
        channel_id=CHANNEL_ID,
        channel_revision="1",
        lane="approval",
        interaction="approval",
        port="request",
    )


def _bound_command_request(message_id: Digest) -> dict[str, JsonValue]:
    return {**APPROVAL_REQUEST, "request_message_id": str(message_id)}


def _force_impossible_reply(
    journal: SqliteJournal,
    *,
    request_id: Digest,
    approval: ApprovalRecord,
    command_id: str,
    observed_at: datetime,
) -> ChannelMessage:
    """Seed one torn row below the public interaction dispatch guard."""

    with journal._txn() as connection:
        return reply_in_transaction(
            connection,
            channel_id=CHANNEL_ID,
            request_id=request_id,
            actor_id=ACTOR.actor_id,
            payload=approval_decision_payload(approval),
            command_id=command_id,
            observe=lambda: observed_at,
        )


def _force_impossible_approval(
    journal: SqliteJournal,
    approval: ApprovalRecord,
    *,
    command_id: str,
) -> None:
    """Seed an approval-only subset below the atomic public writer."""

    with journal._txn() as connection:
        connection.execute(
            "INSERT INTO approvals (approval_id, run_id, subject_json, decision,"
            " reason, actor_json, command_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                approval.approval_id,
                approval.run_id,
                canonical_json(approval.subject.model_dump(mode="json")),
                approval.decision,
                approval.reason,
                approval.actor.model_dump_json(),
                command_id,
                approval.created_at.isoformat(),
            ),
        )
        row = connection.execute(
            "SELECT * FROM approvals WHERE approval_id = ?",
            (approval.approval_id,),
        ).fetchone()
        assert row is not None
        seal_approval(connection, row)


def _force_impossible_ack(
    journal: SqliteJournal,
    *,
    request_id: Digest,
    command_id: str,
    observed_at: datetime,
) -> None:
    """Seed the acknowledgement-only half of a current command transaction."""

    with journal._txn() as connection:
        connection.execute(
            "INSERT INTO channel_acks (message_id, actor_id, command_id, acked_at,"
            " ack_provenance_version) VALUES (?, ?, ?, ?, 1)",
            (
                str(request_id),
                ACTOR.actor_id,
                command_id,
                observed_at.isoformat(),
            ),
        )
        row = connection.execute(
            "SELECT * FROM channel_acks WHERE message_id = ? AND actor_id = ?",
            (str(request_id), ACTOR.actor_id),
        ).fetchone()
        assert row is not None
        record = ChannelAckRecord(
            ack=ChannelAck(
                message_id=request_id,
                actor_id=ACTOR.actor_id,
                acked_at=observed_at,
            ),
            command_id=command_id,
            provenance_version=1,
        )
        # This deliberately impossible half-transaction is still an exact
        # individual fact; the exchange relation, not seal absence, is under test.
        store_durable_fact_seal(
            connection,
            family=CHANNEL_ACK_FACT_FAMILY,
            fact_key=_channel_ack_fact_key(record),
            selector=str(row["ack_seq"]),
            fact_hash=channel_ack_fact_hash(
                row,
                record=record,
                connection=connection,
            ),
        )


def _bound_plan(
    approval: ApprovalRecord,
    request: ChannelMessage,
) -> StoredApprovalPlan:
    assert request.reply_port is not None
    return StoredApprovalPlan(
        plan=ChannelApprovalPlan(
            approval=approval,
            channel_id=request.channel_id,
            request_id=request.message_id,
            reply_id=reply_message_id(
                request_id=request.message_id,
                reply_port=request.reply_port,
            ),
            reply_port=request.reply_port,
            payload=approval_decision_payload(approval),
            ack_actor_id=ACTOR.actor_id,
            run_id=approval.run_id,
            parked_event_seq=0,
        )
    )


def _store_bound_plan(
    journal: SqliteJournal,
    claim: CommandClaim,
    approval: ApprovalRecord,
    request: ChannelMessage,
) -> None:
    journal.store_command_plan(
        claim,
        _bound_plan(approval, request).model_dump(mode="json"),
    )


@pytest.mark.parametrize("partial", ("approval", "approval_ack", "reply", "ack"))
def test_an_approval_exchange_never_repairs_a_partial_transaction(
    partial: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal = SqliteJournal(tmp_path / "partial-approval.db", now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    claimed = _claim(
        journal,
        owner="approval-owner",
        key=f"partial-{partial}",
        operation="runs_approve",
        request=_bound_command_request(_canonical_request_id()),
    )
    assert claimed.claim is not None
    claim = claimed.claim
    approval = _approval(claim)
    request = channel.append_request(_approval_intent(approval), ATTESTATION)
    _store_bound_plan(journal, claim, approval, request)
    payload = approval_decision_payload(approval)

    if partial in {"approval", "approval_ack"}:
        _force_impossible_approval(
            journal,
            approval,
            command_id=claim.command_id,
        )
        if partial == "approval_ack":
            _force_impossible_ack(
                journal,
                request_id=request.message_id,
                command_id=claim.command_id,
                observed_at=clock.now(),
            )
    elif partial == "reply":
        _force_impossible_reply(
            journal,
            request_id=request.message_id,
            approval=approval,
            command_id=claim.command_id,
            observed_at=clock.now(),
        )
    else:
        _force_impossible_ack(
            journal,
            request_id=request.message_id,
            command_id=claim.command_id,
            observed_at=clock.now(),
        )

    with pytest.raises(JournalDamaged):
        journal.store_approval_exchange(
            claim,
            approval,
            channel_id=CHANNEL_ID,
            request_id=request.message_id,
            payload=payload,
        )

    with sqlite3.connect(journal._db_path) as connection:
        approval_exists = connection.execute(
            "SELECT 1 FROM approvals WHERE approval_id = ?",
            (approval.approval_id,),
        ).fetchone() is not None
    assert approval_exists is (partial in {"approval", "approval_ack"})
    if partial == "reply":
        with pytest.raises(JournalDamaged, match="without the approval record"):
            channel.reply_for(request.message_id)
    else:
        assert channel.reply_for(request.message_id) is None


def test_a_preexisting_ack_is_not_a_partial_approval_exchange(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal = SqliteJournal(tmp_path / "preacked-approval.db", now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    claimed = _claim(
        journal,
        owner="approval-owner",
        key="preacked",
        operation="runs_approve",
        request=_bound_command_request(_canonical_request_id()),
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    request = channel.append_request(_approval_intent(approval), ATTESTATION)
    _store_bound_plan(journal, claimed.claim, approval, request)
    ack_with_command(
        channel,
        message_id=request.message_id,
        actor_id=ACTOR.actor_id,
        idempotency_key="prior-approval-ack",
    )

    reply = journal.store_approval_exchange(
        claimed.claim,
        approval,
        channel_id=CHANNEL_ID,
        request_id=request.message_id,
        payload=approval_decision_payload(approval),
    )
    assert channel.reply_for(request.message_id) == reply
    acknowledgement = journal.channel_ack(
        message_id=request.message_id,
        actor_id=ACTOR.actor_id,
    )
    assert acknowledgement is not None
    assert acknowledgement.command_id == ack_command_id(
        ACTOR.actor_id,
        "prior-approval-ack",
    )


def test_the_writer_refuses_a_redirected_plan_before_any_exchange_fact(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "redirected-approval-plan-write.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    claimed = _claim(
        journal,
        owner="redirected-plan",
        key="redirected-plan",
        operation="runs_approve",
        request=_bound_command_request(_canonical_request_id()),
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    request = channel.append_request(_approval_intent(approval), ATTESTATION)
    stored = _bound_plan(approval, request)
    assert isinstance(stored.plan, ChannelApprovalPlan)
    redirected = stored.model_copy(
        update={
            "plan": stored.plan.model_copy(update={"channel_id": "channel/redirected"})
        }
    )
    journal.store_command_plan(claimed.claim, redirected.model_dump(mode="json"))

    with pytest.raises(JournalDamaged, match="sealed request"):
        journal.store_approval_exchange(
            claimed.claim,
            approval,
            channel_id=CHANNEL_ID,
            request_id=request.message_id,
            payload=approval_decision_payload(approval),
        )

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM channel_messages WHERE kind = 'reply'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM channel_acks").fetchone()[0] == 0


def test_the_transaction_refuses_a_noncanonical_approval_exchange(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal = SqliteJournal(tmp_path / "noncanonical-approval.db", now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    intent = _advice_intent(recipient=ACTOR.actor_id)
    claimed = _claim(
        journal,
        owner="approval-owner",
        key="noncanonical",
        operation="runs_approve",
        request=_bound_command_request(intent.message_id),
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    request = channel.append_request(intent, ATTESTATION)
    _store_bound_plan(journal, claimed.claim, approval, request)

    with pytest.raises(JournalDamaged, match="canonical human-approval"):
        journal.store_approval_exchange(
            claimed.claim,
            approval,
            channel_id=CHANNEL_ID,
            request_id=request.message_id,
            payload=approval_decision_payload(approval),
        )

    assert journal.approval(approval.approval_id) is None
    assert channel.reply_for(request.message_id) is None
    delivery = journal.channel_delivery(
        message_id=request.message_id,
        actor_id=ACTOR.actor_id,
    )
    assert delivery is not None and not delivery.acknowledged


@pytest.mark.parametrize("mismatch", ("actor", "run"))
def test_the_transaction_binds_the_command_actor_and_request_run(
    mismatch: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal = SqliteJournal(tmp_path / f"mismatched-approval-{mismatch}.db", now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    claimed = _claim(
        journal,
        owner="approval-owner",
        key=f"mismatched-{mismatch}",
        operation="runs_approve",
        request=_bound_command_request(_canonical_request_id()),
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    request = channel.append_request(_approval_intent(approval), ATTESTATION)
    _store_bound_plan(journal, claimed.claim, approval, request)
    if mismatch == "actor":
        divergent = approval.model_copy(
            update={
                "actor": approval.actor.model_copy(
                    update={"display_name": "a different authenticated principal"}
                )
            }
        )
        match = "actor contradicts its authenticated command"
    else:
        divergent = approval.model_copy(update={"run_id": "run-somewhere-else"})
        match = "canonical command request"

    with pytest.raises(JournalDamaged, match=match):
        journal.store_approval_exchange(
            claimed.claim,
            divergent,
            channel_id=CHANNEL_ID,
            request_id=request.message_id,
            payload=approval_decision_payload(divergent),
        )

    assert journal.approval(divergent.approval_id) is None
    assert channel.reply_for(request.message_id) is None
    delivery = journal.channel_delivery(
        message_id=request.message_id,
        actor_id=ACTOR.actor_id,
    )
    assert delivery is not None and not delivery.acknowledged


def test_reply_and_implied_ack_share_the_transaction_observation_time(tmp_path: Path) -> None:
    class TickingClock:
        def __init__(self) -> None:
            self.value = datetime(2026, 1, 1, tzinfo=UTC)

        def now(self) -> datetime:
            observed = self.value
            self.value += timedelta(seconds=1)
            return observed

    ticking = TickingClock()
    journal = SqliteJournal(tmp_path / "approval-observed-at.db", now_fn=ticking.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    claimed = _claim(
        journal,
        owner="approval-owner",
        key="one-observation",
        operation="runs_approve",
        request=_bound_command_request(_canonical_request_id()),
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    request = channel.append_request(_approval_intent(approval), ATTESTATION)
    _store_bound_plan(journal, claimed.claim, approval, request)

    reply = journal.store_approval_exchange(
        claimed.claim,
        approval,
        channel_id=CHANNEL_ID,
        request_id=request.message_id,
        payload=approval_decision_payload(approval),
    )
    acknowledgement = journal.channel_ack(
        message_id=request.message_id,
        actor_id=ACTOR.actor_id,
    )
    assert acknowledgement is not None
    assert reply.envelope.created_at == acknowledgement.ack.acked_at


def test_an_exact_approval_exchange_retry_needs_no_new_observation(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    class RefusingClock:
        refuse = False

        def now(self) -> datetime:
            if self.refuse:
                raise RuntimeError("timestamp unavailable")
            return clock.now()

    observed = RefusingClock()
    journal = SqliteJournal(tmp_path / "approval-retry-clock.db", now_fn=observed.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    claimed = _claim(
        journal,
        owner="approval-owner",
        key="retry-without-clock",
        operation="runs_approve",
        request=_bound_command_request(_canonical_request_id()),
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    request = channel.append_request(_approval_intent(approval), ATTESTATION)
    _store_bound_plan(journal, claimed.claim, approval, request)
    arguments = {
        "channel_id": CHANNEL_ID,
        "request_id": request.message_id,
        "payload": approval_decision_payload(approval),
    }
    first = journal.store_approval_exchange(claimed.claim, approval, **arguments)

    observed.refuse = True
    replayed = journal.store_approval_exchange(claimed.claim, approval, **arguments)

    assert replayed == first
    assert journal.approval(approval.approval_id) == approval


def test_every_reply_read_refuses_an_approval_missing_from_its_atomic_triple(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "torn-approval-read.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    claimed = _claim(
        journal,
        owner="approval-reader",
        key="torn-approval-reader",
        operation="runs_approve",
        request=_bound_command_request(_canonical_request_id()),
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    request = channel.append_request(_approval_intent(approval), ATTESTATION)
    _store_bound_plan(journal, claimed.claim, approval, request)
    reply = journal.store_approval_exchange(
        claimed.claim,
        approval,
        channel_id=CHANNEL_ID,
        request_id=request.message_id,
        payload=approval_decision_payload(approval),
    )

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "DELETE FROM approvals WHERE approval_id = ?",
            (approval.approval_id,),
        )
        connection.commit()

    match = "without the approval record"
    with pytest.raises(JournalDamaged, match=match):
        channel.message(reply.message_id)
    with pytest.raises(JournalDamaged, match=match):
        channel.reply_for(request.message_id)
    with pytest.raises(JournalDamaged, match=match):
        journal.channel_delivery(message_id=reply.message_id, actor_id=ACTOR.actor_id)
    with pytest.raises(JournalDamaged, match=match):
        journal.channel_message_command(message_id=reply.message_id)
    with pytest.raises(JournalDamaged, match=match):
        journal.answered_requests([request.message_id])


def test_exact_reads_and_wake_refuse_an_approval_id_not_minted_by_its_command(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "forged-approval-identity.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    claimed = _claim(
        journal,
        owner="approval-identity-reader",
        key="approval-identity-reader",
        operation="runs_approve",
        request=_bound_command_request(_canonical_request_id()),
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    request = channel.append_request(_approval_intent(approval), ATTESTATION)
    _store_bound_plan(journal, claimed.claim, approval, request)
    reply = journal.store_approval_exchange(
        claimed.claim,
        approval,
        channel_id=CHANNEL_ID,
        request_id=request.message_id,
        payload=approval_decision_payload(approval),
    )
    forged = approval.model_copy(update={"approval_id": "approval-forged"})
    forged_envelope = reply.envelope.model_copy(
        update={"payload": approval_decision_payload(forged)}
    )

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "UPDATE approvals SET approval_id = ? WHERE approval_id = ?",
            (forged.approval_id, approval.approval_id),
        )
        connection.execute(
            "UPDATE channel_messages SET envelope_json = ? WHERE message_id = ?",
            (forged_envelope.model_dump_json(), str(reply.message_id)),
        )
        approval_row = connection.execute(
            "SELECT * FROM approvals WHERE approval_id = ?",
            (forged.approval_id,),
        ).fetchone()
        reply_row = connection.execute(
            "SELECT * FROM channel_messages WHERE message_id = ?",
            (str(reply.message_id),),
        ).fetchone()
        assert approval_row is not None and reply_row is not None
        approval_seal = connection.execute(
            "UPDATE durable_fact_seals SET fact_key = ?, fact_hash = ?"
            " WHERE family = ? AND fact_key = ? AND selector = ?",
            (
                forged.approval_id,
                # Relocate the seal *and* rebind it to the identity it moved
                # to: the forgery is as coordinated as one can be, and the
                # command-minting proof below must still refuse it.
                str(
                    sealed_fact_hash(
                        family=_APPROVAL_FACT_FAMILY,
                        fact_key=forged.approval_id,
                        selector=claimed.claim.command_id,
                        fact=approval_fact_hash(approval_row),
                    )
                ),
                _APPROVAL_FACT_FAMILY,
                approval.approval_id,
                claimed.claim.command_id,
            ),
        )
        reseal_primary_fact(
            connection,
            family=CHANNEL_MESSAGE_FACT_FAMILY,
            fact_key=str(reply.message_id),
            fact=channel_message_fact_hash(reply_row),
        )
        assert approval_seal.rowcount == 1
        connection.commit()

    match = "was not minted by command"
    with pytest.raises(JournalDamaged, match=match):
        journal.approval(forged.approval_id)
    with pytest.raises(JournalDamaged, match=match):
        channel.reply_for(request.message_id)
    with pytest.raises(JournalDamaged, match=match):
        journal.answered_requests([request.message_id])


@pytest.mark.parametrize("tamper", ("standalone", "channel_id"))
def test_exact_reads_and_wake_bind_an_approval_to_its_channel_plan(
    tamper: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "downgraded-approval-plan.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request_id = _canonical_request_id()
    claimed = _claim(
        journal,
        owner="approval-plan-reader",
        key="approval-plan-reader",
        operation="runs_approve",
        request=_bound_command_request(request_id),
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    request = channel.append_request(_approval_intent(approval), ATTESTATION)
    _store_bound_plan(journal, claimed.claim, approval, request)
    reply = journal.store_approval_exchange(
        claimed.claim,
        approval,
        channel_id=CHANNEL_ID,
        request_id=request.message_id,
        payload=approval_decision_payload(approval),
    )

    with sqlite3.connect(database) as connection:
        if tamper == "standalone":
            damaged_plan = StoredApprovalPlan(
                plan=ApprovalPlan(approval=approval)
            ).model_dump_json()
        else:
            row = connection.execute(
                "SELECT plan_json FROM commands WHERE command_id = ?",
                (claimed.claim.command_id,),
            ).fetchone()
            assert row is not None
            parsed = json.loads(row[0])
            parsed["plan"]["channel_id"] = "channel/redirected"
            damaged_plan = canonical_json(parsed)
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (damaged_plan, claimed.claim.command_id),
        )
        connection.commit()

    with pytest.raises(JournalDamaged):
        journal.approval(approval.approval_id)
    with pytest.raises(JournalDamaged):
        channel.message(reply.message_id)
    with pytest.raises(JournalDamaged):
        channel.reply_for(request.message_id)
    with pytest.raises(JournalDamaged):
        journal.channel_ack(
            message_id=request.message_id,
            actor_id=ACTOR.actor_id,
        )
    with pytest.raises(JournalDamaged):
        journal.answered_requests([request.message_id])


def test_a_current_approval_reply_cannot_erase_its_writer_column(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """A v1 provenance marker and a NULL writer are an impossible mixed era."""

    database = tmp_path / "null-approval-writer.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request_id = _canonical_request_id()
    claimed = _claim(
        journal,
        owner="null-approval-writer",
        key="null-approval-writer",
        operation="runs_approve",
        request=_bound_command_request(request_id),
    )
    assert claimed.claim is not None
    approval = _approval(claimed.claim)
    request = channel.append_request(_approval_intent(approval), ATTESTATION)
    _store_bound_plan(journal, claimed.claim, approval, request)
    reply = journal.store_approval_exchange(
        claimed.claim,
        approval,
        channel_id=CHANNEL_ID,
        request_id=request.message_id,
        payload=approval_decision_payload(approval),
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE channel_messages SET command_id = NULL WHERE message_id = ?",
            (str(reply.message_id),),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable fact"):
        channel.message(reply.message_id)
    with pytest.raises(JournalDamaged, match="not a valid durable fact"):
        journal.answered_requests([request.message_id])
