"""The wake lookup must survive scale and refuse an unverified relationship."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.channel_commands import (
    ack_command_id,
    ack_with_command,
    prepare_reply_command,
    reply_command_id,
    reply_with_command,
)
from tests.channel_requests import (
    AttestedMailboxChannel as MailboxChannel,
)
from tests.channel_requests import (
    mint_send_attestation,
)
from tests.conftest import FakeClock
from tests.durable_seals import reseal_primary_fact
from tests.substrate.channels.test_channel_contract import (
    ADVISOR,
    ATTESTATION,
    CHANNEL_ID,
    _intent,
)

from constructicon.core.address import ExecutionPath, IterationFrame, ScopePath
from constructicon.core.channel import reply_message_id
from constructicon.core.control import READ_SCOPE, AuthenticatedActor, CommandClaim
from constructicon.core.errors import JournalDamaged
from constructicon.core.human import validated_channel_command_reply
from constructicon.core.identity import Digest, canonical_json, digest, json_value
from constructicon.substrate.journal._sqlite_channels import (
    CHANNEL_ACK_FACT_FAMILY,
    CHANNEL_MESSAGE_FACT_FAMILY,
    channel_ack_fact_hash,
    channel_message_fact_hash,
)
from constructicon.substrate.journal._sqlite_commands import (
    command_claim_fact_hash,
    command_plan_fact_hash,
)
from constructicon.substrate.journal.sqlite import SqliteJournal


def _rewrite_message_positive_seal(
    journal: SqliteJournal,
    message_id: Digest,
) -> None:
    """Keep a coordinated corruption behind the independent row seal.

    Tests using this helper are aimed at a deeper relationship or command-plan
    proof.  Ordinary single-row corruption must never call it: the positive
    seal is precisely the boundary that should catch that case first.
    """

    with journal._txn() as connection:
        row = connection.execute(
            "SELECT * FROM channel_messages WHERE message_id = ?",
            (str(message_id),),
        ).fetchone()
        assert row is not None
        reseal_primary_fact(
            connection,
            family=CHANNEL_MESSAGE_FACT_FAMILY,
            fact_key=str(message_id),
            fact=channel_message_fact_hash(row),
        )


def _rewrite_ack_positive_seal(
    journal: SqliteJournal,
    *,
    message_id: Digest,
    actor_id: str,
) -> None:
    """Keep a valid-scalar ack mutation behind its independent row seal."""

    with journal._txn() as connection:
        row = connection.execute(
            "SELECT * FROM channel_acks WHERE message_id = ? AND actor_id = ?",
            (str(message_id), actor_id),
        ).fetchone()
        assert row is not None
        reseal_primary_fact(
            connection,
            family=CHANNEL_ACK_FACT_FAMILY,
            fact_key=canonical_json(
                {
                    "actor_id": actor_id,
                    "message_id": str(message_id),
                }
            ),
            fact=channel_ack_fact_hash(row, connection=connection),
        )


def test_a_page_of_many_waiting_requests_does_not_exceed_the_bind_limit(
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One placeholder per request would break SQLite's variable ceiling.

    Lowering SQLite's limit preserves the same boundary with a small fixture;
    the exception would otherwise escape into the recovery pump.
    """

    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    requests = [
        mailbox.append_request(_intent(port=f"request-{index}"), ATTESTATION).message_id
        for index in range(11)
    ]

    original_connect = journal._connect

    def limited_connect() -> sqlite3.Connection:
        connection = original_connect()
        connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 10)
        return connection

    monkeypatch.setattr(journal, "_connect", limited_connect)
    assert journal.answered_requests(requests) == {}  # no reply exists for any


def test_wake_chunks_distinct_preack_and_reply_command_provenance(
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two lawful writer commands per request must not double the bind ceiling."""

    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    requests: list[Digest] = []
    for index in range(11):
        request = mailbox.append_request(
            _intent(port=f"preacked-request-{index}"),
            ATTESTATION,
        )
        ack_with_command(
            mailbox,
            message_id=request.message_id,
            actor_id=ADVISOR,
            idempotency_key=f"preack-{index}",
        )
        reply_with_command(
            mailbox,
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": index},
            idempotency_key=f"reply-after-preack-{index}",
        )
        requests.append(request.message_id)

    original_connect = journal._connect

    def limited_connect() -> sqlite3.Connection:
        connection = original_connect()
        connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 20)
        return connection

    monkeypatch.setattr(journal, "_connect", limited_connect)
    answered = journal.answered_requests(requests)
    assert set(answered) == set(requests)


def test_duplicate_requests_are_asked_about_once(journal: SqliteJournal) -> None:
    request = MailboxChannel(journal, channel_id=CHANNEL_ID).append_request(
        _intent(),
        ATTESTATION,
    )
    assert journal.answered_requests([request.message_id] * 5_000) == {}


def test_a_valid_message_timestamp_mutation_contradicts_its_positive_seal(
    journal: SqliteJournal,
) -> None:
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    with sqlite3.connect(journal._db_path) as connection:
        envelope = json.loads(
            connection.execute(
                "SELECT envelope_json FROM channel_messages WHERE message_id = ?",
                (str(request.message_id),),
            ).fetchone()[0]
        )
        envelope["created_at"] = "2030-01-01T00:00:00Z"
        connection.execute(
            "UPDATE channel_messages SET envelope_json = ? WHERE message_id = ?",
            (canonical_json(json_value(envelope)), str(request.message_id)),
        )

    with pytest.raises(JournalDamaged, match="contradicts its positive seal"):
        mailbox.message(request.message_id)


def test_a_valid_ack_timestamp_mutation_contradicts_its_positive_seal(
    journal: SqliteJournal,
) -> None:
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    ack_with_command(
        mailbox,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key="positive-ack-seal",
    )
    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "UPDATE channel_acks SET acked_at = ?"
            " WHERE message_id = ? AND actor_id = ?",
            ("2030-01-01T00:00:00+00:00", str(request.message_id), ADVISOR),
        )

    with pytest.raises(JournalDamaged, match="contradicts its positive seal"):
        journal.channel_ack(message_id=request.message_id, actor_id=ADVISOR)


def test_a_valid_channel_cutoff_mutation_contradicts_its_positive_seal(
    journal: SqliteJournal,
) -> None:
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    mailbox.append_request(_intent(), ATTESTATION)
    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "UPDATE channel_provenance SET legacy_message_through = 1"
            " WHERE singleton = 1"
        )

    with pytest.raises(JournalDamaged, match="contradicts its positive seal"):
        mailbox.latest_revision(ADVISOR)


def test_a_relocated_message_cannot_hide_from_its_derived_identity(
    journal: SqliteJournal,
) -> None:
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    relocated = digest("relocated-channel-message", 1, {})
    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "UPDATE channel_messages SET message_id = ? WHERE message_id = ?",
            (str(relocated), str(request.message_id)),
        )

    with pytest.raises(JournalDamaged, match="disappeared behind their positive seals"):
        mailbox.message(request.message_id)


@pytest.mark.parametrize("projection", ("exact", "inbox"))
def test_a_relocated_ack_cannot_hide_from_its_delivery_identity(
    projection: str,
    journal: SqliteJournal,
) -> None:
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(port="relocated-ack"), ATTESTATION)
    hidden = mailbox.append_request(
        _intent(port="hidden-ack-target", recipient="static:other"),
        ATTESTATION,
    )
    ack_with_command(
        mailbox,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key=f"relocated-ack-{projection}",
    )
    revision = mailbox.latest_revision(ADVISOR)
    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "UPDATE channel_acks SET message_id = ? WHERE message_id = ? AND actor_id = ?",
            (str(hidden.message_id), str(request.message_id), ADVISOR),
        )

    with pytest.raises(JournalDamaged, match="positive seal"):
        if projection == "exact":
            journal.channel_ack(message_id=request.message_id, actor_id=ADVISOR)
        else:
            mailbox.inbox(
                actor_id=ADVISOR,
                revision=revision,
                after=None,
                limit=10,
            )


def test_an_inbox_chunks_ack_rows_and_positive_keys_below_the_bind_limit(
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    for index in range(11):
        request = mailbox.append_request(
            _intent(port=f"inbox-ack-chunk-{index}"),
            ATTESTATION,
        )
        ack_with_command(
            mailbox,
            message_id=request.message_id,
            actor_id=ADVISOR,
            idempotency_key=f"inbox-ack-chunk-{index}",
        )
    revision = mailbox.latest_revision(ADVISOR)
    original_connect = journal._connect

    def limited_connect() -> sqlite3.Connection:
        connection = original_connect()
        connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 10)
        return connection

    monkeypatch.setattr(journal, "_connect", limited_connect)
    page = mailbox.inbox(
        actor_id=ADVISOR,
        revision=revision,
        after=None,
        limit=11,
    )
    assert len(page) == 11
    assert all(delivery.acknowledged for delivery in page)


def test_a_reply_pointer_that_does_not_derive_from_its_request_is_damage(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """A `reply_to` pointer alone must never be treated as a relationship."""

    database = tmp_path / "tampered.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    answered = mailbox.append_request(_intent(), ATTESTATION)
    other = mailbox.append_request(_intent(port="second-request"), ATTESTATION)
    reply = reply_with_command(
        mailbox,
        request_id=answered.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-1",
    )
    assert journal.answered_requests([answered.message_id]) == {
        answered.message_id: reply.message_id
    }

    # Repoint the stored reply at the other request without changing anything
    # else — exactly what a tampered or damaged row looks like.
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE channel_messages SET reply_to = ? WHERE message_id = ?",
            (str(other.message_id), str(reply.message_id)),
        )
        connection.commit()
    _rewrite_message_positive_seal(journal, reply.message_id)

    reopened = journal
    with pytest.raises(JournalDamaged, match="contradicts the request"):
        reopened.answered_requests([other.message_id])

    # And the read that would have handed a run that payload refuses too.
    with pytest.raises(JournalDamaged, match="contradicts the request"):
        MailboxChannel(reopened, channel_id=CHANNEL_ID).reply_for(other.message_id)


def test_a_genuine_reply_still_resolves(tmp_path: Path, clock: FakeClock) -> None:
    journal = SqliteJournal(tmp_path / "genuine.db", now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    reply = reply_with_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-1",
    )
    assert reply.message_id == reply_message_id(
        request_id=request.message_id,
        reply_port="reply",
    )
    assert mailbox.reply_for(request.message_id) == reply
    assert journal.answered_requests([request.message_id]) == {
        request.message_id: reply.message_id
    }
    acknowledgement = journal.channel_ack(
        message_id=request.message_id,
        actor_id=ADVISOR,
    )
    assert acknowledgement is not None
    assert acknowledgement.command_id == reply_command_id(ADVISOR, "cmd-1")
    assert acknowledgement.ack.message_id == request.message_id
    assert acknowledgement.ack.actor_id == ADVISOR


def test_reply_ownership_decodes_its_durable_message_identity(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "damaged-owned-reply.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    reply = reply_with_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="owned-reply-identity",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE channel_messages SET message_id = 'bad' WHERE message_id = ?",
            (str(reply.message_id),),
        )

    with pytest.raises(JournalDamaged, match="not a valid durable fact"):
        reply_with_command(
            mailbox,
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            idempotency_key="owned-reply-identity",
        )
    with pytest.raises(
        JournalDamaged,
        match=r"not a valid durable fact|disappeared behind their positive seals",
    ):
        journal.answered_requests([request.message_id])


@pytest.mark.parametrize("projection", ("exact", "ack", "wake"))
def test_a_reply_payload_must_match_its_writer_plan(
    projection: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """A derived id and valid relationship do not authenticate reply payload."""

    database = tmp_path / f"reply-plan-{projection}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    reply = reply_with_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": 1},
        idempotency_key=f"payload-{projection}",
    )
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT envelope_json FROM channel_messages WHERE message_id = ?",
            (str(reply.message_id),),
        ).fetchone()
        assert row is not None
        envelope = json.loads(row[0])
        envelope["payload"] = {"advice": True}
        connection.execute(
            "UPDATE channel_messages SET envelope_json = ? WHERE message_id = ?",
            (canonical_json(json_value(envelope)), str(reply.message_id)),
        )
        connection.commit()
    _rewrite_message_positive_seal(journal, reply.message_id)

    reopened = journal
    with pytest.raises(JournalDamaged, match="independently stored proof"):
        if projection == "exact":
            MailboxChannel(reopened, channel_id=CHANNEL_ID).message(reply.message_id)
        elif projection == "ack":
            reopened.channel_ack(message_id=request.message_id, actor_id=ADVISOR)
        else:
            reopened.answered_requests([request.message_id])


@pytest.mark.parametrize("projection", ("ack", "reply", "wake"))
def test_an_implied_ack_shares_its_replys_exact_observation_time(
    projection: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / f"reply-ack-observation-{projection}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    reply_with_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key=f"reply-ack-observation-{projection}",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE channel_acks SET acked_at = ? WHERE message_id = ? AND actor_id = ?",
            ("2030-01-01T00:00:00+00:00", str(request.message_id), ADVISOR),
        )
    _rewrite_ack_positive_seal(
        journal,
        message_id=request.message_id,
        actor_id=ADVISOR,
    )

    reopened = journal
    with pytest.raises(JournalDamaged, match="atomic observation"):
        if projection == "ack":
            reopened.channel_ack(message_id=request.message_id, actor_id=ADVISOR)
        elif projection == "reply":
            MailboxChannel(reopened, channel_id=CHANNEL_ID).reply_for(request.message_id)
        else:
            reopened.answered_requests([request.message_id])


def test_wake_reproves_a_preexisting_explicit_ack_plan(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "wake-preack-plan.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    ack_with_command(
        mailbox,
        message_id=request.message_id,
        actor_id=ADVISOR,
        idempotency_key="wake-preack",
    )
    reply_with_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="wake-after-preack",
    )
    command_id = ack_command_id(ADVISOR, "wake-preack")
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "UPDATE commands SET plan_json = json_set("
            "plan_json, '$.plan.channel_id', 'channel/forged') WHERE command_id = ?",
            (command_id,),
        )
        row = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None
        reseal_primary_fact(
            connection,
            family="command_plan",
            fact_key=command_id,
            fact=command_plan_fact_hash(row),
        )

    with pytest.raises(JournalDamaged, match="contradicts its command"):
        journal.answered_requests([request.message_id])


def test_a_reply_command_must_hold_the_request_sealed_authority(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """A typed plan does not turn an unauthorized actor into an advisor."""

    database = tmp_path / "reply-authority.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    command_id = prepare_reply_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="reply-without-advice-authority",
    )
    read_only_actor = AuthenticatedActor(
        actor_id=ADVISOR,
        auth_method="static",
        scopes=frozenset({READ_SCOPE}),
    )
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            "UPDATE commands SET actor_json = ? WHERE command_id = ?",
            (
                canonical_json(json_value(read_only_actor.model_dump(mode="json"))),
                command_id,
            ),
        )
        row = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None
        reseal_primary_fact(
            connection,
            family="command_claim",
            fact_key=command_id,
            fact=command_claim_fact_hash(row),
        )
        connection.commit()

    reopened = journal
    with pytest.raises(JournalDamaged, match="contradicts its command"):
        MailboxChannel(reopened, channel_id=CHANNEL_ID).reply(
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            command_id=command_id,
        )
    assert MailboxChannel(reopened, channel_id=CHANNEL_ID).reply_for(request.message_id) is None
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM channel_acks"
            " WHERE message_id = ? AND actor_id = ?",
            (str(request.message_id), ADVISOR),
        ).fetchone() == (0,)


def test_an_invalid_reply_plan_is_typed_durable_damage(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "invalid-reply-plan.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    reply = reply_with_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="invalid-plan",
    )
    command_id = reply_command_id(ADVISOR, "invalid-plan")
    record = journal.command(command_id)
    assert record is not None
    assert record.plan is not None
    invalid_plan = json.loads(canonical_json(record.plan))
    invalid_plan["plan"]["payload"] = float("nan")
    with pytest.raises(JournalDamaged, match="invalid reply plan") as wrapped:
        validated_channel_command_reply(
            record.model_copy(update={"plan": invalid_plan}),
            request,
            reply,
        )
    assert isinstance(wrapped.value.__cause__, ValueError)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (json.dumps(invalid_plan), command_id),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        MailboxChannel(
            SqliteJournal(database, now_fn=clock.now),
            channel_id=CHANNEL_ID,
        ).message(reply.message_id)
    assert isinstance(damaged.value.__cause__, ValueError)


def test_a_first_reply_cannot_repair_a_terminal_command_without_its_fact(
    journal: SqliteJournal,
) -> None:
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    command_id = prepare_reply_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="terminal-without-reply",
    )
    record = journal.command(command_id)
    assert record is not None
    assert record.owner_id is not None
    assert record.lease_expires_at is not None
    journal.complete_command(
        CommandClaim(
            command_id=record.command_id,
            actor_id=record.actor.actor_id,
            operation=record.operation,
            owner_id=record.owner_id,
            epoch=record.owner_epoch,
            expires_at=record.lease_expires_at,
        ),
        {"status": "committed-without-domain-fact"},
    )

    with pytest.raises(JournalDamaged, match="belongs to a terminal command"):
        mailbox.reply(
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            command_id=command_id,
        )
    assert mailbox.reply_for(request.message_id) is None
    assert journal.channel_ack(message_id=request.message_id, actor_id=ADVISOR) is None


def test_a_channel_envelope_is_decoded_without_scalar_coercion(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "lossy-envelope.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    path = ExecutionPath(
        scope=ScopePath(segments=("review",)),
        iterations=(
            IterationFrame(
                loop=ScopePath(segments=("review", "loop")),
                index=1,
            ),
        ),
    )
    request = MailboxChannel(journal, channel_id=CHANNEL_ID).append_request(
        _intent(path=path),
        ATTESTATION,
    )
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT envelope_json FROM channel_messages WHERE message_id = ?",
            (str(request.message_id),),
        ).fetchone()
        assert row is not None
        envelope = json.loads(row[0])
        envelope["path"]["iterations"][0]["index"] = True
        connection.execute(
            "UPDATE channel_messages SET envelope_json = ? WHERE message_id = ?",
            (json.dumps(envelope), str(request.message_id)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable fact"):
        MailboxChannel(
            SqliteJournal(database, now_fn=clock.now),
            channel_id=CHANNEL_ID,
        ).message(request.message_id)


def test_a_channel_envelope_cannot_collapse_duplicate_payload_keys(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "duplicate-envelope.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    request = MailboxChannel(journal, channel_id=CHANNEL_ID).append_request(
        _intent(),
        ATTESTATION,
    )
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT envelope_json FROM channel_messages WHERE message_id = ?",
            (str(request.message_id),),
        ).fetchone()
        assert row is not None
        raw = str(row[0])
        duplicated = raw.replace(
            '"payload":',
            '"payload":{"question":"forged"},"payload":',
            1,
        )
        assert duplicated != raw
        connection.execute(
            "UPDATE channel_messages SET envelope_json = ? WHERE message_id = ?",
            (duplicated, str(request.message_id)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable fact") as damaged:
        MailboxChannel(
            SqliteJournal(database, now_fn=clock.now),
            channel_id=CHANNEL_ID,
        ).message(request.message_id)
    assert isinstance(damaged.value.__cause__, ValueError)
    assert "repeats key 'payload'" in str(damaged.value.__cause__)


def test_an_invalid_persisted_recipient_is_durable_journal_damage(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "invalid-recipient.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    request = MailboxChannel(journal, channel_id=CHANNEL_ID).append_request(
        _intent(),
        ATTESTATION,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE channel_messages SET recipient_actor_id = ? WHERE message_id = ?",
            ("advisor", str(request.message_id)),
        )
        connection.commit()

    reopened = journal
    with pytest.raises(
        JournalDamaged,
        match=rf"channel message {str(request.message_id)!r} is not a valid durable fact",
    ) as damaged:
        MailboxChannel(reopened, channel_id=CHANNEL_ID).message(request.message_id)
    assert isinstance(damaged.value.__cause__, ValidationError)


@pytest.mark.parametrize(
    ("target", "column", "value"),
    (
        ("request", "attestation_id", None),
        ("request", "command_id", "cmd-forged-request-authority"),
        ("reply", "attestation_id", "att-forged-reply-authority"),
        ("reply", "recipient_actor_id", ADVISOR),
    ),
)
def test_channel_rows_refuse_an_impossible_authority_shape(
    target: str,
    column: str,
    value: str | None,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / f"invalid-{target}-{column}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    message = (
        reply_with_command(
        mailbox,
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            idempotency_key="cmd-reply-authority",
        )
        if target == "reply"
        else request
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE channel_messages SET {column} = ? WHERE message_id = ?",
            (value, str(message.message_id)),
        )
        connection.commit()

    reopened = journal
    with pytest.raises(
        JournalDamaged,
        match=rf"channel message {str(message.message_id)!r} is not a valid durable fact",
    ):
        MailboxChannel(reopened, channel_id=CHANNEL_ID).message(message.message_id)


@pytest.mark.parametrize("projection", ("exact", "inbox", "wake"))
def test_every_request_projection_refuses_an_envelope_that_disagrees_with_its_row(
    projection: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / f"request-envelope-{projection}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    if projection == "wake":
        reply_with_command(
        mailbox,
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            idempotency_key="cmd-envelope-wake",
        )
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT envelope_json FROM channel_messages WHERE message_id = ?",
            (str(request.message_id),),
        ).fetchone()
        assert row is not None
        envelope = json.loads(row[0])
        if projection == "exact":
            envelope["run_id"] = "run-forged"
        elif projection == "inbox":
            envelope["path"]["scope"]["segments"] = ["forged"]
        else:
            envelope["port"] = "forged-port"
        connection.execute(
            "UPDATE channel_messages SET envelope_json = ? WHERE message_id = ?",
            (json.dumps(envelope), str(request.message_id)),
        )
        connection.commit()

    reopened = journal
    with pytest.raises(
        JournalDamaged,
        match=rf"channel message {str(request.message_id)!r} is not a valid durable fact",
    ):
        if projection == "exact":
            MailboxChannel(reopened, channel_id=CHANNEL_ID).message(request.message_id)
        elif projection == "inbox":
            reopened.channel_inbox(
                channel_id=CHANNEL_ID,
                actor_id=ADVISOR,
                revision=reopened.channel_revision(channel_id=CHANNEL_ID),
                after=None,
                limit=10,
            )
        else:
            reopened.answered_requests([request.message_id])


def test_an_invalid_persisted_ack_actor_is_durable_journal_damage(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "invalid-ack-actor.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    reply_with_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-invalid-ack-actor",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE channel_acks SET actor_id = ? WHERE message_id = ? AND actor_id = ?",
            ("advisor", str(request.message_id), ADVISOR),
        )
        connection.commit()

    reopened = journal
    with pytest.raises(
        JournalDamaged,
        match=rf"channel acknowledgement for message {str(request.message_id)!r}",
    ) as damaged:
        reopened.channel_ack(message_id=request.message_id, actor_id="advisor")
    assert isinstance(damaged.value.__cause__, ValidationError)


@pytest.mark.parametrize("projection", ("delivery", "inbox", "reply", "wake"))
def test_every_acknowledgement_projection_decodes_the_durable_fact(
    projection: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / f"invalid-ack-{projection}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    reply_with_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key=f"invalid-ack-{projection}",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE channel_acks SET acked_at = ? WHERE message_id = ? AND actor_id = ?",
            ("not-a-time", str(request.message_id), ADVISOR),
        )
        connection.commit()

    reopened = journal
    with pytest.raises(JournalDamaged, match="channel acknowledgement"):
        if projection == "delivery":
            reopened.channel_delivery(message_id=request.message_id, actor_id=ADVISOR)
        elif projection == "inbox":
            reopened.channel_inbox(
                channel_id=CHANNEL_ID,
                actor_id=ADVISOR,
                revision=reopened.channel_revision(channel_id=CHANNEL_ID),
                after=None,
                limit=10,
            )
        elif projection == "reply":
            MailboxChannel(reopened, channel_id=CHANNEL_ID).reply_for(request.message_id)
        else:
            reopened.answered_requests([request.message_id])


def test_an_invalid_persisted_attestation_recipient_is_durable_journal_damage(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "invalid-attestation-recipient.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    attestation = mint_send_attestation(journal, _intent())
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT attestation_json FROM attestations WHERE attestation_id = ?",
            (attestation.attestation_id,),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["subject"]["recipient_actor_id"] = "advisor"
        connection.execute(
            "UPDATE attestations SET attestation_json = ? WHERE attestation_id = ?",
            (json.dumps(payload), attestation.attestation_id),
        )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match=rf"attestation {attestation.attestation_id!r} is not a valid durable record",
    ) as damaged:
        SqliteJournal(database, now_fn=clock.now)
    assert isinstance(damaged.value.__cause__, ValidationError)


def test_a_reply_without_its_atomic_ack_is_damage_and_is_never_healed(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "torn-reply.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    reply = reply_with_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-torn",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM channel_acks WHERE message_id = ? AND actor_id = ?",
            (str(request.message_id), ADVISOR),
        )
        connection.commit()

    reopened = journal
    torn = MailboxChannel(reopened, channel_id=CHANNEL_ID)
    damage = r"acknowledgement|fact-seal inventory"
    with pytest.raises(JournalDamaged, match=damage):
        torn.reply_for(request.message_id)
    with pytest.raises(JournalDamaged, match=damage):
        torn.message(reply.message_id)
    with pytest.raises(JournalDamaged, match=damage):
        reopened.channel_delivery(message_id=reply.message_id, actor_id=ADVISOR)
    with pytest.raises(JournalDamaged, match=damage):
        reopened.channel_message_writer(message_id=reply.message_id)
    with pytest.raises(JournalDamaged, match=damage):
        reply_with_command(
            torn,
            request_id=request.message_id,
            actor_id=ADVISOR,
            payload={"advice": "ship"},
            idempotency_key="cmd-torn",
        )
    with pytest.raises(JournalDamaged, match=damage):
        reopened.answered_requests([request.message_id])
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM channel_acks"
            " WHERE message_id = ? AND actor_id = ?",
            (str(request.message_id), ADVISOR),
        ).fetchone() == (0,)


def test_wake_lookup_validates_the_complete_reply_contract(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "tampered-contract.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    reply = reply_with_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-contract",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE channel_messages SET type_id = ? WHERE message_id = ?",
            ("other/Reply", str(reply.message_id)),
        )
        connection.commit()
    _rewrite_message_positive_seal(journal, reply.message_id)

    reopened = journal
    with pytest.raises(JournalDamaged, match="contradicts the request"):
        reopened.answered_requests([request.message_id])


def test_a_parked_wait_whose_request_disappeared_is_damage(
    journal: SqliteJournal,
) -> None:
    missing = digest("channel-message", 1, {"absent": True})
    with pytest.raises(JournalDamaged, match="requests that are not stored"):
        journal.answered_requests([missing])


def test_a_parked_wait_cannot_name_a_reply(journal: SqliteJournal) -> None:
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    request = mailbox.append_request(_intent(), ATTESTATION)
    reply = reply_with_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key="cmd-non-request-wait",
    )
    with pytest.raises(JournalDamaged, match="non-request message"):
        journal.answered_requests([reply.message_id])
