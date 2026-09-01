"""Durable channel requests remain bound to one run's admitted authority."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.channel_commands import reply_with_command
from tests.channel_requests import mint_send_attestation
from tests.run_attestations import ensure_test_run
from tests.substrate.channels.test_channel_contract import (
    ADVISOR,
    CHANNEL_ID,
    RUN,
    _intent,
)

from constructicon.core.address import RunId
from constructicon.core.channel import CHANNEL_SEND_EFFECT, ChannelSendIntent
from constructicon.core.effect import (
    AttestationDraft,
    CheckResult,
    EffectRequest,
    attestation_id_for,
    channel_send_subject,
    idempotency_key,
)
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import Digest, canonical_json, digest, json_value
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.journal.sqlite import SqliteJournal

FOREIGN_RUN = RunId("run-foreign-channel-authority")


class RefusingClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 1, 1, tzinfo=UTC)
        self.calls = 0
        self.refuse = False

    def now(self) -> datetime:
        if self.refuse:
            raise AssertionError("invalid channel authority observed time")
        self.calls += 1
        return self.value


def _draft(
    *,
    manifest_hash: Digest,
    intent: ChannelSendIntent,
) -> AttestationDraft:
    return AttestationDraft(
        action="send",
        subject=channel_send_subject(intent),
        checks=(
            CheckResult(
                name="channel-send",
                status="passed",
                detail="test authority",
                elapsed_s=0.0,
            ),
        ),
        check_set_hash=digest("check-set", 1, {"test": "request-provenance"}),
        manifest_hash=manifest_hash,
    )


def _journal(tmp_path: Path, name: str) -> tuple[SqliteJournal, RefusingClock, Path]:
    database = tmp_path / f"{name}.db"
    clock = RefusingClock()
    return SqliteJournal(database, now_fn=clock.now), clock, database


def _rewrite_attestation_root(
    database: Path,
    attestation_id: str,
    *,
    created_by_run: RunId,
) -> None:
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT attestation_json FROM attestations WHERE attestation_id = ?",
            (attestation_id,),
        ).fetchone()
        assert row is not None
        payload = json.loads(row[0])
        payload["created_by_run"] = str(created_by_run)
        connection.execute(
            "UPDATE attestations SET attestation_json = ? WHERE attestation_id = ?",
            (canonical_json(json_value(payload)), attestation_id),
        )
        connection.commit()


def _corrupt_request_authority(
    fault: str,
    *,
    journal: SqliteJournal,
    database: Path,
    request_id: str,
    attestation_id: str,
) -> None:
    if fault == "missing":
        with sqlite3.connect(database) as connection:
            connection.execute(
                "DELETE FROM attestations WHERE attestation_id = ?",
                (attestation_id,),
            )
            connection.commit()
        return
    if fault == "foreign_subject":
        foreign = mint_send_attestation(journal, _intent(port="foreign-proof"))
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE channel_messages SET attestation_id = ? WHERE message_id = ?",
                (foreign.attestation_id, request_id),
            )
            connection.commit()
        return
    if fault == "foreign_run":
        _rewrite_attestation_root(
            database,
            attestation_id,
            created_by_run=FOREIGN_RUN,
        )
        return
    if fault == "foreign_manifest":
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE runs SET manifest_hash = ? WHERE run_id = ?",
                (str(digest("manifest", 1, {"world": "foreign"})), str(RUN)),
            )
            connection.commit()
        return
    raise AssertionError(f"unknown authority fault {fault!r}")


@pytest.mark.parametrize(
    "fault",
    ("missing", "foreign_subject", "foreign_run", "foreign_manifest"),
)
def test_a_fresh_request_refuses_invalid_authority_before_observing_time(
    fault: str,
    tmp_path: Path,
) -> None:
    journal, clock, database = _journal(tmp_path, f"fresh-{fault}")
    manifest_hash = ensure_test_run(journal, RUN)
    intent = _intent()
    proof = mint_send_attestation(journal, intent)
    attestation_id = proof.attestation_id
    if fault == "missing":
        attestation_id = "att-missing"
    elif fault == "foreign_subject":
        attestation_id = mint_send_attestation(
            journal,
            _intent(port="foreign-proof"),
        ).attestation_id
    elif fault == "foreign_run":
        _rewrite_attestation_root(
            database,
            proof.attestation_id,
            created_by_run=FOREIGN_RUN,
        )
    else:
        assert fault == "foreign_manifest"
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE runs SET manifest_hash = ? WHERE run_id = ?",
                (str(digest("manifest", 1, {"world": "foreign"})), str(RUN)),
            )
            connection.commit()
    assert manifest_hash == proof.manifest_hash
    calls = clock.calls
    clock.refuse = True

    with pytest.raises(JournalDamaged):
        MailboxChannel(journal, channel_id=CHANNEL_ID).append_request(
            intent,
            attestation_id,
        )

    assert clock.calls == calls
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM channel_messages").fetchone() == (0,)


def test_policy_minting_cannot_authorize_a_run_send(tmp_path: Path) -> None:
    journal, clock, _database = _journal(tmp_path, "policy-send")
    manifest_hash = ensure_test_run(journal, RUN)
    draft = _draft(manifest_hash=manifest_hash, intent=_intent())
    calls = clock.calls
    clock.refuse = True

    with pytest.raises(ContractViolation, match="promotion only"):
        journal.mint_policy_attestation(draft)

    assert clock.calls == calls
    assert journal.load_attestation(attestation_id_for(draft)) is None


def test_a_run_cannot_mint_send_authority_for_another_run(tmp_path: Path) -> None:
    journal, clock, _database = _journal(tmp_path, "foreign-run-mint")
    manifest_hash = ensure_test_run(journal, RUN)
    ensure_test_run(journal, FOREIGN_RUN, manifest_hash=manifest_hash)
    draft = _draft(manifest_hash=manifest_hash, intent=_intent())
    lease = journal.claim_run(FOREIGN_RUN, owner_id="foreign-owner", ttl_s=30)
    calls = clock.calls
    clock.refuse = True

    with pytest.raises(ContractViolation, match="names another run"):
        journal.mint_attestation(lease, draft)

    assert clock.calls == calls
    assert journal.load_attestation(attestation_id_for(draft)) is None


def test_a_run_cannot_mint_authority_from_another_manifest(tmp_path: Path) -> None:
    journal, clock, _database = _journal(tmp_path, "foreign-manifest-mint")
    ensure_test_run(journal, RUN)
    draft = _draft(
        manifest_hash=digest("manifest", 1, {"world": "foreign"}),
        intent=_intent(),
    )
    lease = journal.claim_run(RUN, owner_id="run-owner", ttl_s=30)
    calls = clock.calls
    clock.refuse = True

    with pytest.raises(ContractViolation, match="contradicts its run manifest"):
        journal.mint_attestation(lease, draft)

    assert clock.calls == calls
    assert journal.load_attestation(attestation_id_for(draft)) is None


def test_a_retained_request_prevents_reminting_its_deleted_authority(
    tmp_path: Path,
) -> None:
    journal, clock, database = _journal(tmp_path, "deleted-request-authority")
    manifest_hash = ensure_test_run(journal, RUN)
    intent = _intent()
    draft = _draft(manifest_hash=manifest_hash, intent=intent)
    lease = journal.claim_run(RUN, owner_id="request-authority-owner", ttl_s=30)
    proof = journal.mint_attestation(lease, draft)
    request = MailboxChannel(journal, channel_id=CHANNEL_ID).append_request(
        intent,
        proof.attestation_id,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM attestations WHERE attestation_id = ?",
            (proof.attestation_id,),
        )
        connection.execute(
            "DELETE FROM durable_fact_seals"
            " WHERE family IN ('attestation', 'legacy_attestation_m1_m2')"
            " AND fact_key = ?",
            (proof.attestation_id,),
        )
        connection.commit()
    calls = clock.calls
    clock.refuse = True

    with pytest.raises(JournalDamaged, match="dependent durable fact"):
        journal.load_attestation(proof.attestation_id)
    with pytest.raises(JournalDamaged, match="dependent durable fact"):
        journal.mint_attestation(lease, draft)

    assert clock.calls == calls
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attestations").fetchone() == (0,)
        assert connection.execute(
            "SELECT attestation_id FROM channel_messages WHERE message_id = ?",
            (str(request.message_id),),
        ).fetchone() == (proof.attestation_id,)
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_fact_seals"
            " WHERE family IN ('attestation', 'legacy_attestation_m1_m2')"
            " AND fact_key = ?",
            (proof.attestation_id,),
        ).fetchone() == (0,)


def test_a_channel_message_prevents_repreparing_its_deleted_send_effect(
    tmp_path: Path,
) -> None:
    journal, clock, database = _journal(tmp_path, "deleted-channel-send-preparation")
    manifest_hash = ensure_test_run(journal, RUN)
    intent = _intent(port="deleted-send-preparation")
    proof = mint_send_attestation(journal, intent)
    lease = journal.claim_run(RUN, owner_id="send-preparation-owner", ttl_s=30)
    subject = intent.model_dump(mode="json")
    effect = EffectRequest(
        run_id=RUN,
        manifest_hash=manifest_hash,
        path=intent.path,
        kind=CHANNEL_SEND_EFFECT,
        subject=subject,
        idempotency_key=idempotency_key(
            manifest_hash,
            intent.path,
            CHANNEL_SEND_EFFECT,
            subject,
        ),
        attestation_id=proof.attestation_id,
    )
    assert journal.record_effect_prepared(lease, effect) == effect
    request = MailboxChannel(journal, channel_id=CHANNEL_ID).append_request(
        intent,
        proof.attestation_id,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM effects WHERE idempotency_key = ?",
            (str(effect.idempotency_key),),
        )
        connection.execute(
            "DELETE FROM durable_fact_seals"
            " WHERE family = 'effect_preparation' AND fact_key = ?",
            (str(effect.idempotency_key),),
        )

    calls = clock.calls
    clock.refuse = True
    with pytest.raises(JournalDamaged, match=r"durable message.*without its preparation"):
        journal.record_effect_prepared(lease, effect)
    assert clock.calls == calls

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM effects").fetchone() == (0,)
        assert connection.execute(
            "SELECT message_id FROM channel_messages WHERE message_id = ?",
            (str(request.message_id),),
        ).fetchone() == (str(request.message_id),)


@pytest.mark.parametrize(
    "fault",
    ("missing", "foreign_subject", "foreign_run", "foreign_manifest"),
)
@pytest.mark.parametrize("projection", ("exact", "inbox", "reply", "wake"))
def test_every_request_projection_revalidates_its_run_authority(
    fault: str,
    projection: str,
    tmp_path: Path,
) -> None:
    journal, _clock, database = _journal(tmp_path, f"{projection}-{fault}")
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    intent = _intent()
    proof = mint_send_attestation(journal, intent)
    request = mailbox.append_request(intent, proof.attestation_id)
    reply = reply_with_command(
        mailbox,
        request_id=request.message_id,
        actor_id=ADVISOR,
        payload={"advice": "ship"},
        idempotency_key=f"reply-{projection}-{fault}",
    )
    revision = mailbox.latest_revision(ADVISOR)
    _corrupt_request_authority(
        fault,
        journal=journal,
        database=database,
        request_id=str(request.message_id),
        attestation_id=proof.attestation_id,
    )

    with pytest.raises(JournalDamaged):
        if projection == "exact":
            mailbox.message(request.message_id)
        elif projection == "inbox":
            mailbox.inbox(
                actor_id=ADVISOR,
                revision=revision,
                after=None,
                limit=10,
            )
        elif projection == "reply":
            mailbox.reply_for(request.message_id)
        else:
            assert projection == "wake"
            journal.answered_requests((request.message_id,))

    assert reply.reply_to == request.message_id


def test_wake_batch_refuses_two_requests_claiming_one_send_proof(tmp_path: Path) -> None:
    journal, _clock, database = _journal(tmp_path, "duplicate-proof")
    mailbox = MailboxChannel(journal, channel_id=CHANNEL_ID)
    first_intent = _intent(port="first")
    second_intent = _intent(port="second")
    first_proof = mint_send_attestation(journal, first_intent)
    second_proof = mint_send_attestation(journal, second_intent)
    first = mailbox.append_request(first_intent, first_proof.attestation_id)
    second = mailbox.append_request(second_intent, second_proof.attestation_id)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE channel_messages SET attestation_id = ? WHERE message_id = ?",
            (first_proof.attestation_id, str(second.message_id)),
        )
        connection.commit()

    with pytest.raises(
        JournalDamaged,
        match=r"one send attestation|positive seal",
    ):
        journal.answered_requests((first.message_id, second.message_id))
