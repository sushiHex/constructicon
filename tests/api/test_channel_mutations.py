"""Answering and acknowledging a channel request (M7 PR C).

Two operations, one dispatch rule. `channels_reply` consumes advice and nothing
else — an approval is answered by request-bound `runs_approve`, so holding
approve must never turn this into a generic reply path. An acknowledgement is a
delivery fact, so both interactions are ackable under their own scope, and a
reply is ackable by nobody: no inbox ever surfaces one.

Both refuse in dispatch order — kind, then interaction, then authority — and all
three before the command is claimed, because none of them is a domain outcome.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.channel import (
    ChannelContract,
    ChannelInteraction,
    ChannelSendIntent,
    reply_message_id,
    request_message_id,
)
from constructicon.core.control import (
    ADVISE_SCOPE,
    APPROVE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    ChannelAckResult,
    ChannelReplyResult,
    CommandClaim,
    ControlCode,
    ControlRejected,
    command_id_for,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.human import (
    ADVICE_REPLY_CONTRACT,
    ADVICE_REQUEST_CONTRACT,
    APPROVAL_REPLY_CONTRACT,
    APPROVAL_REQUEST_CONTRACT,
    AdviceReplyPayload,
)
from constructicon.core.identity import Digest, canonical_json, json_value
from constructicon.core.run import RunStatus
from constructicon.substrate.journal._sqlite_channels import (
    CHANNEL_ACK_FACT_FAMILY,
    CHANNEL_MESSAGE_FACT_FAMILY,
    CHANNEL_PROVENANCE_FACT_FAMILY,
    channel_ack_fact_hash,
    channel_message_fact_hash,
    channel_provenance_fact_hash,
    seal_channel_ack,
)
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.channel_requests import AttestedMailboxChannel as MailboxChannel
from tests.conftest import FakeClock, InjectedCrash

CHANNEL_ID = "channel/review"
ADVISOR_ID = "static:advisor"
APPROVER_ID = "static:approver"
RUN = RunId("run-channel-mutations")
PATH = ExecutionPath(scope=ScopePath(segments=("review",)))
REQUEST_CONTRACT = ChannelContract(type_id="test/Ask", schema_hash="ask-v1")
REPLY_CONTRACT = ChannelContract(type_id="test/Answer", schema_hash="answer-v1")
ATTESTATION = "att-channel-mutations"
SEAMS = ("after_plan", "after_domain_mutation", "after_command_completion")


def _actor(actor_id: str, *scopes: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=actor_id,
        auth_method="static",
        scopes=frozenset({READ_SCOPE, *scopes}),
    )


ADVISOR = _actor(ADVISOR_ID, ADVISE_SCOPE)
APPROVER = _actor(APPROVER_ID, APPROVE_SCOPE)
BOTH = _actor(ADVISOR_ID, ADVISE_SCOPE, APPROVE_SCOPE)


class _RecordingHost(RunHost):
    """A host boundary that records wake intent without scheduling anything."""

    def __init__(self) -> None:
        self.launches: list[tuple[RunId, dict[str, Any]]] = []

    def _configure_committed_resumes(self, store: Any, decoder: Any) -> None:
        return None

    async def startup(self) -> None:
        return None

    async def abort_startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    def launch(self, run_id: RunId, **kwargs: Any) -> str:
        self.launches.append((run_id, kwargs))
        return "queued"


def _intent(
    *,
    port: str = "ask",
    recipient: str | None = ADVISOR_ID,
    interaction: ChannelInteraction = "advice",
) -> ChannelSendIntent:
    return ChannelSendIntent(
        message_id=request_message_id(
            run_id=RUN,
            path=PATH,
            channel_id=CHANNEL_ID,
            channel_revision="1",
            lane="review",
            interaction=interaction,
            port=port,
        ),
        channel_id=CHANNEL_ID,
        channel_revision="1",
        lane="review",
        interaction=interaction,
        recipient_actor_id=recipient,
        contract=REQUEST_CONTRACT,
        reply_contract=REPLY_CONTRACT,
        run_id=RUN,
        path=PATH,
        port=port,
        reply_port=f"{port}-answer",
        payload={"question": port},
    )


class _Panel:
    """One control plane, one channel, one journal, one host recorder."""

    def __init__(
        self,
        tmp_path: Path,
        clock: FakeClock,
        system: Constructicon,
        probe: Any,
        owner: str,
    ) -> None:
        self.journal = SqliteJournal(tmp_path / "channel-mutations.db", now_fn=clock.now)
        self.host = _RecordingHost()
        self.channel = MailboxChannel(self.journal, channel_id=CHANNEL_ID)
        local_system = Constructicon(
            journal=self.journal,
            store=system._registry.store,
        )
        self.host._system = local_system
        self.host._journal = self.journal
        self.control = ControlPlane(
            system=local_system,
            store=self.journal,
            run_host=cast(RunHost, self.host),
            owner_id=owner,
            command_ttl_s=30,
            fault_probe=probe,
        )


def _panel(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
    probe: Any = None,
    owner: str = "channel-mutations",
) -> _Panel:
    return _Panel(tmp_path, clock, system, probe, owner)


def _crash_at(target: str) -> Any:
    def crash(name: str) -> None:
        if name == target:
            raise InjectedCrash(name)

    return crash


def _replace_test_only_channel_seal(
    connection: sqlite3.Connection,
    *,
    family: str,
    selector: str,
    fact_hash: Digest,
) -> None:
    """Keep a deliberately rewritten historical fixture internally sealed."""

    updated = connection.execute(
        "UPDATE durable_fact_seals SET fact_hash = ?"
        " WHERE family = ? AND selector = ?",
        (str(fact_hash), family, selector),
    )
    assert updated.rowcount == 1


async def test_a_deleted_reply_command_cannot_be_reclaimed_to_heal_its_fact(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(port="deleted-writer"), ATTESTATION)
    key = "deleted-reply-writer"
    replied = await panel.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "ship"},
        idempotency_key=key,
    )
    assert isinstance(replied, ChannelReplyResult)
    command_id = command_id_for(ADVISOR_ID, "channels_reply", key)
    with sqlite3.connect(panel.journal._db_path) as connection:
        connection.execute(
            "DELETE FROM commands WHERE command_id = ?",
            (command_id,),
        )
        connection.execute(
            "DELETE FROM durable_fact_seals"
            " WHERE fact_key = ?"
            " AND family IN ('command_claim', 'command_plan', 'command_terminal')",
            (command_id,),
        )

    def refuse_time() -> Any:
        raise AssertionError("command deletion healing observed time")

    panel.journal._now = refuse_time
    with pytest.raises(JournalDamaged, match="dependent durable fact"):
        await panel.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key=key,
        )

    with sqlite3.connect(panel.journal._db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM channel_messages WHERE reply_to = ?",
            (str(request.message_id),),
        ).fetchone() == (1,)


async def test_a_deleted_ack_command_and_its_seals_cannot_heal_a_v1_fact(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(port="deleted-ack-writer"), ATTESTATION)
    key = "deleted-ack-writer"
    acked = await panel.control.channels_ack(
        ADVISOR,
        message_id=request.message_id,
        idempotency_key=key,
    )
    assert isinstance(acked, ChannelAckResult)
    command_id = command_id_for(ADVISOR_ID, "channels_ack", key)
    with sqlite3.connect(panel.journal._db_path) as connection:
        connection.execute("DELETE FROM commands WHERE command_id = ?", (command_id,))
        connection.execute(
            "DELETE FROM durable_fact_seals"
            " WHERE fact_key = ?"
            " AND family IN ('command_claim', 'command_plan', 'command_terminal')",
            (command_id,),
        )

    def refuse_time() -> Any:
        raise AssertionError("v1 acknowledgement healing observed time")

    panel.journal._now = refuse_time
    with pytest.raises(JournalDamaged, match="dependent durable fact"):
        await panel.control.channels_ack(
            ADVISOR,
            message_id=request.message_id,
            idempotency_key=key,
        )

    with sqlite3.connect(panel.journal._db_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT ack_provenance_version FROM channel_acks"
            " WHERE message_id = ? AND actor_id = ?",
            (str(request.message_id), ADVISOR_ID),
        ).fetchone() == (1,)


@pytest.mark.parametrize("family", ("reply", "ack"))
async def test_rejection_finds_relocated_channel_facts_from_the_typed_plan(
    family: str,
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    operation = f"channels_{family}"
    key = f"relocated-{family}-owner"
    crashing = _panel(
        tmp_path,
        clock,
        system,
        _crash_at(f"{operation}.after_domain_mutation"),
        "relocated-owner",
    )
    request = crashing.channel.append_request(_intent(), ATTESTATION)
    with pytest.raises(InjectedCrash):
        if family == "reply":
            await crashing.control.channels_reply(
                ADVISOR,
                message_id=request.message_id,
                payload={"verdict": "ship"},
                idempotency_key=key,
            )
        else:
            await crashing.control.channels_ack(
                ADVISOR,
                message_id=request.message_id,
                idempotency_key=key,
            )

    command_id = command_id_for(ADVISOR_ID, operation, key)
    relocated = f"cmd-relocated-{family}-owner"
    with sqlite3.connect(crashing.journal._db_path) as connection:
        if family == "reply":
            connection.execute(
                "UPDATE channel_messages SET command_id = ? WHERE reply_to = ?",
                (relocated, str(request.message_id)),
            )
        connection.execute(
            "UPDATE channel_acks SET command_id = ?"
            " WHERE message_id = ? AND actor_id = ?",
            (relocated, str(request.message_id), ADVISOR_ID),
        )
        connection.commit()

    record = crashing.journal.command(command_id)
    assert record is not None
    assert record.state == "prepared"
    assert record.owner_id is not None
    assert record.lease_expires_at is not None
    claim = CommandClaim(
        command_id=record.command_id,
        actor_id=record.actor.actor_id,
        operation=record.operation,
        owner_id=record.owner_id,
        epoch=record.owner_epoch,
        expires_at=record.lease_expires_at,
    )
    with pytest.raises(JournalDamaged, match=r"command|provenance|positive seal"):
        crashing.journal.reject_command(claim, {"status": "rejected"})

    unchanged = crashing.journal.command(command_id)
    assert unchanged is not None
    assert unchanged.state == "prepared"
    assert unchanged.response is None


async def test_a_reply_is_derived_entirely_from_the_request_it_answers(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """The caller chose a payload. It chose nothing else about the message."""

    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(), ATTESTATION)

    result = await panel.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "ship"},
        idempotency_key="reply-1",
    )
    assert isinstance(result, ChannelReplyResult)
    assert result.message_id == reply_message_id(
        request_id=request.message_id,
        reply_port="ask-answer",
    )

    stored = panel.channel.reply_for(request.message_id)
    assert stored is not None
    assert stored.channel_id == request.channel_id
    assert stored.lane == request.lane
    assert stored.interaction == request.interaction
    assert stored.contract == request.reply_contract
    assert stored.envelope.port == request.reply_port
    assert stored.envelope.run_id == request.envelope.run_id
    assert stored.envelope.path == request.envelope.path
    assert stored.sender_actor_id == ADVISOR_ID
    assert stored.recipient_actor_id is None

    # The request is acknowledged for its author in the reply's transaction.
    delivery = panel.journal.channel_delivery(
        message_id=request.message_id,
        actor_id=ADVISOR_ID,
    )
    assert delivery is not None and delivery.acknowledged

    # One bounded wake intent, pinned to the fence the plan recorded.
    assert len(panel.host.launches) == 1
    run_id, kwargs = panel.host.launches[0]
    assert run_id == RUN
    assert kwargs["allowed_statuses"] == frozenset({RunStatus.PARKED})
    assert kwargs["cause"].kind == "channel_reply"
    assert kwargs["cause"].id == str(result.message_id)
    assert kwargs["expected_event_seq"] == 0


async def test_channels_reply_consumes_advice_and_nothing_else(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """Holding approve must not make this a generic reply path.

    An approval is consumed exclusively by request-bound `runs_approve`, so the
    refusal names the interaction rather than a scope the actor already holds.
    """

    panel = _panel(tmp_path, clock, system)
    approval = panel.channel.append_request(
        _intent(port="gate", recipient=APPROVER_ID, interaction="approval"),
        ATTESTATION,
    )

    refused = await panel.control.channels_reply(
        APPROVER,
        message_id=approval.message_id,
        payload={"decision": "approved"},
        idempotency_key="reply-approval",
    )
    assert isinstance(refused, ControlRejected)
    assert refused.faults[0].code is ControlCode.CHANNEL_WRONG_INTERACTION
    assert refused.faults[0].details == {"interaction": "approval"}
    assert "runs_approve" in refused.faults[0].repair
    assert panel.channel.reply_for(approval.message_id) is None


async def test_the_wrong_interaction_is_refused_before_the_command_is_claimed(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """Dispatch is not a domain outcome, so it burns no idempotency key.

    A durable command record for a message this operation was never going to
    consume would also make the same key unusable against the right operation.
    """

    panel = _panel(tmp_path, clock, system)
    approval = panel.channel.append_request(
        _intent(port="gate", recipient=ADVISOR_ID, interaction="approval"),
        ATTESTATION,
    )
    advice = panel.channel.append_request(_intent(), ATTESTATION)

    refused = await panel.control.channels_reply(
        BOTH,
        message_id=approval.message_id,
        payload={"verdict": "ship"},
        idempotency_key="shared-key",
    )
    assert isinstance(refused, ControlRejected)
    assert panel.journal.latest_command_key(operation="channels_reply") is None

    # The very same key still works against a request this operation consumes.
    accepted = await panel.control.channels_reply(
        BOTH,
        message_id=advice.message_id,
        payload={"verdict": "ship"},
        idempotency_key="shared-key",
    )
    assert isinstance(accepted, ChannelReplyResult)


async def test_an_incoherent_exchange_is_refused_before_the_command_is_claimed(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    panel = _panel(tmp_path, clock, system)
    incoherent_intent = _intent(port="incoherent").model_copy(
        update={
            "contract": APPROVAL_REQUEST_CONTRACT,
            "reply_contract": APPROVAL_REPLY_CONTRACT,
        }
    )
    incoherent = panel.channel.append_request(incoherent_intent, ATTESTATION)

    refused = await panel.control.channels_reply(
        ADVISOR,
        message_id=incoherent.message_id,
        payload={"verdict": "ship"},
        idempotency_key="coherence-shared-key",
    )
    assert isinstance(refused, ControlRejected)
    assert refused.faults[0].code is ControlCode.REQUEST_INVALID
    assert "incoherent exchange" in refused.faults[0].message
    assert panel.journal.latest_command_key(operation="channels_reply") is None
    assert panel.channel.reply_for(incoherent.message_id) is None

    coherent = panel.channel.append_request(_intent(port="coherent"), ATTESTATION)
    accepted = await panel.control.channels_reply(
        ADVISOR,
        message_id=coherent.message_id,
        payload={"verdict": "ship"},
        idempotency_key="coherence-shared-key",
    )
    assert isinstance(accepted, ChannelReplyResult)


async def test_neither_mutation_acts_on_a_reply(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """A reply is never in an inbox, so acknowledging one records a fiction.

    That is decided here rather than inherited from the shared resolver, which
    would happily govern a reply by the request it answers.
    """

    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(), ATTESTATION)
    replied = await panel.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "ship"},
        idempotency_key="direct-reply",
    )
    assert isinstance(replied, ChannelReplyResult)
    reply = panel.channel.message(replied.message_id)
    assert reply is not None

    for refused in (
        await panel.control.channels_reply(
            ADVISOR,
            message_id=reply.message_id,
            payload={"verdict": "again"},
            idempotency_key="reply-to-reply",
        ),
        await panel.control.channels_ack(
            ADVISOR,
            message_id=reply.message_id,
            idempotency_key="ack-a-reply",
        ),
    ):
        assert isinstance(refused, ControlRejected)
        assert refused.faults[0].code is ControlCode.CHANNEL_REQUEST_REQUIRED


async def test_a_different_command_after_an_admitted_reply_is_typed_not_damage(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """One reply per request is a hard constraint, so this is a lost race."""

    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(recipient=None), ATTESTATION)
    first = await panel.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "ship"},
        idempotency_key="race-first",
    )
    assert isinstance(first, ChannelReplyResult)

    for loser, key in ((ADVISOR, "race-second"), (BOTH, "race-third")):
        late = await panel.control.channels_reply(
            loser,
            message_id=request.message_id,
            payload={"verdict": "hold"},
            idempotency_key=key,
        )
        assert isinstance(late, ControlRejected)
        assert late.faults[0].code is ControlCode.CHANNEL_ALREADY_REPLIED

    stored = panel.channel.reply_for(request.message_id)
    assert stored is not None and stored.envelope.payload == {"verdict": "ship"}


async def test_replaying_a_reply_command_returns_the_one_stored_fact(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(), ATTESTATION)
    first = await panel.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "ship"},
        idempotency_key="replay-me",
    )
    assert isinstance(first, ChannelReplyResult)

    again = await panel.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "ship"},
        idempotency_key="replay-me",
    )
    assert isinstance(again, ChannelReplyResult)
    assert again.command.replayed
    assert again.model_dump(exclude={"command"}) == first.model_dump(exclude={"command"})


async def test_terminal_reply_replay_requires_the_reply_to_belong_to_its_command(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(), ATTESTATION)
    result = await panel.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "ship"},
        idempotency_key="terminal-writer",
    )
    assert isinstance(result, ChannelReplyResult)

    with sqlite3.connect(panel.journal._db_path) as raw:
        raw.execute(
            "UPDATE channel_messages SET command_id = ? WHERE message_id = ?",
            ("cmd-forged-writer", str(result.message_id)),
        )

    with pytest.raises(JournalDamaged, match=r"command|positive seal"):
        await panel.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="terminal-writer",
        )


@pytest.mark.parametrize("seam", SEAMS)
async def test_a_reply_survives_every_response_loss_seam(
    seam: str,
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """A death at any seam replays one exact fact, never a second reply."""

    crashing = _panel(tmp_path, clock, system, _crash_at(f"channels_reply.{seam}"), "crash")
    request = crashing.channel.append_request(_intent(), ATTESTATION)
    with pytest.raises(InjectedCrash):
        await crashing.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="seam",
        )

    clock.advance(31)  # the crashed worker's short claim expires
    recovered = _panel(tmp_path, clock, system, None, "recovery")
    result = await recovered.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "ship"},
        idempotency_key="seam",
    )
    assert isinstance(result, ChannelReplyResult)
    assert result.command.replayed is (seam == "after_command_completion")
    stored = recovered.channel.reply_for(request.message_id)
    assert stored is not None
    assert stored.message_id == result.message_id
    assert canonical_json(json_value(stored.envelope.payload)) == canonical_json(
        {"verdict": "ship"}
    )
    delivery = recovered.journal.channel_delivery(
        message_id=request.message_id,
        actor_id=ADVISOR_ID,
    )
    assert delivery is not None and delivery.acknowledged


async def test_an_acknowledgement_follows_the_requests_own_interaction(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """Both interactions are delivered, each under the scope its request seals."""

    panel = _panel(tmp_path, clock, system)
    advice = panel.channel.append_request(_intent(), ATTESTATION)
    approval = panel.channel.append_request(
        _intent(port="gate", recipient=APPROVER_ID, interaction="approval"),
        ATTESTATION,
    )

    acked = await panel.control.channels_ack(
        ADVISOR,
        message_id=advice.message_id,
        idempotency_key="ack-advice",
    )
    assert isinstance(acked, ChannelAckResult)
    assert acked.actor_id == ADVISOR_ID

    approved = await panel.control.channels_ack(
        APPROVER,
        message_id=approval.message_id,
        idempotency_key="ack-approval",
    )
    assert isinstance(approved, ChannelAckResult)

    # An advisor may not acknowledge an approval it was never addressed by.
    refused = await panel.control.channels_ack(
        ADVISOR,
        message_id=approval.message_id,
        idempotency_key="ack-not-mine",
    )
    assert isinstance(refused, ControlRejected)
    assert refused.faults[0].code is ControlCode.AUTH_REQUIRED_SCOPE


async def test_one_delivery_fact_has_one_owning_command(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """A second command over the same fact is a duplicate, never damage."""

    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(), ATTESTATION)
    first = await panel.control.channels_ack(
        ADVISOR,
        message_id=request.message_id,
        idempotency_key="ack-first",
    )
    assert isinstance(first, ChannelAckResult)

    second = await panel.control.channels_ack(
        ADVISOR,
        message_id=request.message_id,
        idempotency_key="ack-second",
    )
    assert isinstance(second, ControlRejected)
    assert second.faults[0].code is ControlCode.IDEMPOTENCY_CONFLICT

    replayed = await panel.control.channels_ack(
        ADVISOR,
        message_id=request.message_id,
        idempotency_key="ack-first",
    )
    assert isinstance(replayed, ChannelAckResult)
    assert replayed.command.replayed
    assert replayed.acked_at == first.acked_at


@pytest.mark.parametrize("tamper", ["owner", "time"])
async def test_terminal_ack_replay_validates_its_exact_owned_fact(
    tamper: str,
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(), ATTESTATION)
    result = await panel.control.channels_ack(
        ADVISOR,
        message_id=request.message_id,
        idempotency_key="terminal-ack",
    )
    assert isinstance(result, ChannelAckResult)
    command_id = command_id_for(ADVISOR_ID, "channels_ack", "terminal-ack")

    with sqlite3.connect(panel.journal._db_path) as raw:
        if tamper == "owner":
            raw.execute(
                "UPDATE channel_acks SET command_id = ? WHERE message_id = ? AND actor_id = ?",
                ("cmd-forged-owner", str(request.message_id), ADVISOR_ID),
            )
        else:
            row = raw.execute(
                "SELECT response_json FROM commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            assert row is not None
            response = json.loads(row[0])
            response["acked_at"] = "2030-01-01T00:00:00Z"
            raw.execute(
                "UPDATE commands SET response_json = ? WHERE command_id = ?",
                (json.dumps(response, sort_keys=True, separators=(",", ":")), command_id),
            )

    with pytest.raises(
        JournalDamaged,
        match=(
            r"ack response|invalid command provenance|positive seal|"
            r"missing behind a dependent durable fact"
        ),
    ):
        await panel.control.channels_ack(
            ADVISOR,
            message_id=request.message_id,
            idempotency_key="terminal-ack",
        )


@pytest.mark.parametrize("seam", SEAMS)
async def test_an_acknowledgement_survives_every_response_loss_seam(
    seam: str,
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    crashing = _panel(tmp_path, clock, system, _crash_at(f"channels_ack.{seam}"), "crash")
    request = crashing.channel.append_request(_intent(), ATTESTATION)
    with pytest.raises(InjectedCrash):
        await crashing.control.channels_ack(
            ADVISOR,
            message_id=request.message_id,
            idempotency_key="ack-seam",
        )

    clock.advance(31)  # the crashed worker's short claim expires
    recovered = _panel(tmp_path, clock, system, None, "recovery")
    result = await recovered.control.channels_ack(
        ADVISOR,
        message_id=request.message_id,
        idempotency_key="ack-seam",
    )
    assert isinstance(result, ChannelAckResult)
    assert result.command.replayed is (seam == "after_command_completion")
    assert result.message_id == request.message_id


async def test_an_unknown_message_never_reaches_a_command(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    panel = _panel(tmp_path, clock, system)
    absent = Digest(str(_intent(port="never-sent").message_id))

    refused = await panel.control.channels_reply(
        ADVISOR,
        message_id=absent,
        payload={"verdict": "ship"},
        idempotency_key="ghost",
    )
    assert isinstance(refused, ControlRejected)
    assert refused.faults[0].code is ControlCode.CHANNEL_MESSAGE_UNKNOWN
    assert panel.journal.latest_command_key(operation="channels_reply") is None


def _canonical_advice(port: str = "ask") -> ChannelSendIntent:
    """One request typed by the canonical advice contracts."""

    return _intent(port=port).model_copy(
        update={
            "contract": ADVICE_REQUEST_CONTRACT,
            "reply_contract": ADVICE_REPLY_CONTRACT,
        }
    )


async def test_authorship_is_stamped_by_the_executor_not_the_answer(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """`ask()` returns only the payload, so authority must be written into it.

    A component that promises "who advised" would otherwise be repeating a
    claim the payload made about itself. The advisor supplies advice; the
    executor supplies the authenticated actor and the derived reply identity.
    """

    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_canonical_advice(), ATTESTATION)

    # The answer even tries to author its own authorship. It is data, not claim.
    result = await panel.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "ship", "actor_id": "static:someone-else"},
        idempotency_key="stamped",
    )
    assert isinstance(result, ChannelReplyResult)

    stored = panel.channel.reply_for(request.message_id)
    assert stored is not None
    carried = AdviceReplyPayload.model_validate(stored.envelope.payload)
    assert carried.actor_id == ADVISOR_ID
    assert carried.message_id == result.message_id
    assert carried.advice == {"verdict": "ship", "actor_id": "static:someone-else"}


async def test_an_uncanonical_advice_channel_stores_exactly_what_was_written(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """The request's sealed reply contract decides, not the executor.

    Only the canonical exchange promises authorship, so only it is stamped;
    every other advice channel gets the answer verbatim.
    """

    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(), ATTESTATION)
    await panel.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "ship"},
        idempotency_key="verbatim",
    )
    stored = panel.channel.reply_for(request.message_id)
    assert stored is not None
    assert stored.envelope.payload == {"verdict": "ship"}


async def test_a_tampered_plan_cannot_apply_itself(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """A plan is never its own evidence.

    Every field it carries is re-derived from the sealed request on the way
    back in, so a plan edited between the crash and the retry cannot hand the
    run a fact the request never authorized.
    """

    crashing = _panel(tmp_path, clock, system, _crash_at("channels_reply.after_plan"), "crash")
    request = crashing.channel.append_request(_canonical_advice(port="tamper"), ATTESTATION)
    with pytest.raises(InjectedCrash):
        await crashing.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="tamper",
        )

    command_id = command_id_for(ADVISOR_ID, "channels_reply", "tamper")
    with sqlite3.connect(crashing.journal._db_path) as raw:
        row = raw.execute(
            "SELECT plan_json FROM commands WHERE command_id = ?", (command_id,)
        ).fetchone()
        stored = json.loads(row[0])
        stored["plan"]["payload"]["actor_id"] = "static:someone-else"
        raw.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (json.dumps(stored), command_id),
        )

    clock.advance(31)
    with pytest.raises(JournalDamaged, match=r"sealed request|positive seal"):
        recovered = _panel(tmp_path, clock, system, None, "recovery")
        await recovered.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="tamper",
        )
    assert crashing.channel.reply_for(request.message_id) is None


async def test_acknowledging_a_request_does_not_forfeit_the_right_to_answer_it(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """An acknowledgement is a delivery observation, not a consumed right.

    A reply does not *claim* a delivery fact, it implies one: the actor plainly
    received the request it is answering. Requiring the reply's own command to
    own that row would mean an actor who acknowledged a request before
    answering it could never answer it, and for an addressed request nobody
    else could either.
    """

    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(), ATTESTATION)

    acked = await panel.control.channels_ack(
        ADVISOR,
        message_id=request.message_id,
        idempotency_key="ack-first",
    )
    assert isinstance(acked, ChannelAckResult)

    replied = await panel.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "ship"},
        idempotency_key="reply-after-ack",
    )
    assert isinstance(replied, ChannelReplyResult)
    stored = panel.channel.reply_for(request.message_id)
    assert stored is not None and stored.message_id == replied.message_id


async def test_reply_implied_ack_is_a_lawful_foreign_ack_owner(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """A reply authors its implied delivery fact under the reply command."""

    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(), ATTESTATION)
    replied = await panel.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "ship"},
        idempotency_key="reply-owning-ack",
    )
    assert isinstance(replied, ChannelReplyResult)

    for _ in range(2):
        duplicate = await panel.control.channels_ack(
            ADVISOR,
            message_id=request.message_id,
            idempotency_key="ack-after-reply",
        )
        assert isinstance(duplicate, ControlRejected)
        assert duplicate.faults[0].code is ControlCode.IDEMPOTENCY_CONFLICT


async def test_a_lost_race_past_preflight_is_typed_not_an_exception(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """Two commands can both seal plans before either domain write, then one loses.

    Planning and the domain write are not one transaction, so the loser must
    learn it lost the same way a late caller does — a typed refusal, never an
    exception with a stranded plan.
    """

    crashing = _panel(tmp_path, clock, system, _crash_at("channels_reply.after_plan"), "racer")
    request = crashing.channel.append_request(_intent(), ATTESTATION)
    with pytest.raises(InjectedCrash):
        await crashing.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="racer",
        )

    # A second command passes preflight and commits the one reply.
    winner = _panel(tmp_path, clock, system, None, "winner")
    won = await winner.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "hold"},
        idempotency_key="winner",
    )
    assert isinstance(won, ChannelReplyResult)

    # The first command resumes holding a plan, so it never re-runs preflight.
    clock.advance(31)
    resumed = _panel(tmp_path, clock, system, None, "racer-again")
    lost = await resumed.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "ship"},
        idempotency_key="racer",
    )
    assert isinstance(lost, ControlRejected)
    assert lost.faults[0].code is ControlCode.CHANNEL_ALREADY_REPLIED
    stored = resumed.channel.reply_for(request.message_id)
    assert stored is not None and stored.envelope.payload == {"verdict": "hold"}


async def test_terminal_rejection_revalidates_its_plan_at_the_write_boundary(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crashing = _panel(tmp_path, clock, system, _crash_at("channels_reply.after_plan"), "racer")
    request = crashing.channel.append_request(_intent(), ATTESTATION)
    with pytest.raises(InjectedCrash):
        await crashing.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="rejection-boundary",
        )
    winner = _panel(tmp_path, clock, system, None, "winner")
    won = await winner.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "hold"},
        idempotency_key="rejection-boundary-winner",
    )
    assert isinstance(won, ChannelReplyResult)

    clock.advance(31)
    recovered = _panel(tmp_path, clock, system, None, "recovered")
    command_id = command_id_for(ADVISOR_ID, "channels_reply", "rejection-boundary")
    prove_winner = recovered.control._commands._require_foreign_reply

    def tamper_after_winner_proof(**kwargs: Any) -> Any:
        writer = prove_winner(**kwargs)
        with sqlite3.connect(recovered.journal._db_path) as raw:
            row = raw.execute(
                "SELECT plan_json FROM commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            assert row is not None
            stored = json.loads(row[0])
            stored["plan"]["payload"]["actor_id"] = "static:someone-else"
            raw.execute(
                "UPDATE commands SET plan_json = ? WHERE command_id = ?",
                (json.dumps(stored), command_id),
            )
        return writer

    monkeypatch.setattr(
        recovered.control._commands,
        "_require_foreign_reply",
        tamper_after_winner_proof,
    )
    with pytest.raises(JournalDamaged, match=r"sealed request|positive seal"):
        await recovered.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="rejection-boundary",
        )

    # The deliberately corrupted command no longer has a public projection.
    # Inspect only the two mutation columns to prove the refused write left it
    # prepared and response-free.
    with sqlite3.connect(recovered.journal._db_path) as raw:
        stored_command = raw.execute(
            "SELECT state, response_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
    assert stored_command == ("prepared", None)


async def test_a_late_reply_loser_plans_before_it_observes_and_reproves_the_winner(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """Even an already-lost command crosses the durable domain-plan boundary."""

    winner = _panel(tmp_path, clock, system, None, "winner")
    request = winner.channel.append_request(_intent(), ATTESTATION)
    won = await winner.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "hold"},
        idempotency_key="late-winner",
    )
    assert isinstance(won, ChannelReplyResult)

    crashing = _panel(
        tmp_path,
        clock,
        system,
        _crash_at("channels_reply.after_plan"),
        "late-loser",
    )
    with pytest.raises(InjectedCrash):
        await crashing.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="late-loser",
        )

    loser_id = command_id_for(ADVISOR_ID, "channels_reply", "late-loser")
    winner_id = command_id_for(ADVISOR_ID, "channels_reply", "late-winner")
    with sqlite3.connect(crashing.journal._db_path) as raw:
        row = raw.execute(
            "SELECT plan_json FROM commands WHERE command_id = ?",
            (loser_id,),
        ).fetchone()
        assert row is not None
        assert json.loads(row[0])["plan"]["kind"] == "channel_reply"
        # A reply row is not self-authenticating. Tear its writer's durable plan
        # before the loser retries; replay must not turn the orphan into evidence.
        raw.execute(
            "UPDATE commands SET plan_json = NULL WHERE command_id = ?",
            (winner_id,),
        )

    clock.advance(31)
    with pytest.raises(
        JournalDamaged,
        match=r"not a valid durable record|missing or precedes its sealed phase",
    ):
        recovered = _panel(tmp_path, clock, system, None, "late-loser-recovery")
        await recovered.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="late-loser",
        )


async def test_a_lost_reply_replays_its_refusal(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """Losing a race is a terminal answer, so it has to repeat like any other."""

    crashing = _panel(tmp_path, clock, system, _crash_at("channels_reply.after_plan"), "crash")
    request = crashing.channel.append_request(_intent(), ATTESTATION)
    with pytest.raises(InjectedCrash):
        await crashing.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="replay-loser",
        )

    winner = _panel(tmp_path, clock, system, None, "winner")
    won = await winner.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "hold"},
        idempotency_key="replay-winner",
    )
    assert isinstance(won, ChannelReplyResult)

    clock.advance(31)
    resumed = _panel(tmp_path, clock, system, None, "resumed")
    for _ in range(2):
        lost = await resumed.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="replay-loser",
        )
        assert isinstance(lost, ControlRejected)
        assert lost.faults[0].code is ControlCode.CHANNEL_ALREADY_REPLIED
    command_id = command_id_for(ADVISOR_ID, "channels_reply", "replay-loser")
    with sqlite3.connect(resumed.journal._db_path) as raw:
        row = raw.execute(
            "SELECT response_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None
        response_json = str(row[0])
        response = json.loads(response_json)
        response["faults"][0]["message"] = "forged refusal"
        raw.execute(
            "UPDATE commands SET response_json = ? WHERE command_id = ?",
            (json.dumps(response, sort_keys=True, separators=(",", ":")), command_id),
        )

    with pytest.raises(JournalDamaged, match=r"canonical response|positive seal"):
        await resumed.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="replay-loser",
        )

    with sqlite3.connect(resumed.journal._db_path) as raw:
        raw.execute(
            "UPDATE commands SET response_json = ? WHERE command_id = ?",
            (response_json, command_id),
        )
        row = raw.execute(
            "SELECT envelope_json FROM channel_messages WHERE message_id = ?",
            (str(won.message_id),),
        ).fetchone()
        assert row is not None
        forged_envelope = json.loads(row[0])
        forged_envelope["payload"] = {"verdict": "forged"}
        raw.execute(
            "UPDATE channel_messages SET envelope_json = ? WHERE message_id = ?",
            (
                json.dumps(forged_envelope, sort_keys=True, separators=(",", ":")),
                str(won.message_id),
            ),
        )

    # A well-related row is still not evidence unless its writer's immutable
    # plan names these exact bytes.
    with pytest.raises(
        JournalDamaged,
        match=r"independently stored proof|positive seal",
    ):
        await resumed.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="replay-loser",
        )


async def test_a_new_command_can_truthfully_lose_to_an_opaque_v6_reply(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """Historical opacity does not turn an ordinary lost race into damage."""

    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(), ATTESTATION)
    won = await panel.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": "hold"},
        idempotency_key="legacy-winner",
    )
    assert isinstance(won, ChannelReplyResult)
    winner_id = command_id_for(ADVISOR_ID, "channels_reply", "legacy-winner")
    with sqlite3.connect(panel.journal._db_path) as raw:
        raw.row_factory = sqlite3.Row
        ack = raw.execute(
            "SELECT ack_seq FROM channel_acks WHERE message_id = ? AND actor_id = ?",
            (str(request.message_id), ADVISOR_ID),
        ).fetchone()
        assert ack is not None
        reply_seq = raw.execute(
            "SELECT message_seq FROM channel_messages WHERE message_id = ?",
            (str(won.message_id),),
        ).fetchone()
        assert reply_seq is not None
        raw.execute(
            "UPDATE channel_messages SET command_id = NULL,"
            " reply_provenance_version = NULL WHERE message_id = ?",
            (str(won.message_id),),
        )
        raw.execute(
            "UPDATE channel_acks SET ack_provenance_version = 0"
            " WHERE message_id = ? AND actor_id = ?",
            (str(request.message_id), ADVISOR_ID),
        )
        raw.execute(
            "UPDATE channel_provenance SET legacy_ack_through = ?,"
            " legacy_message_through = ? WHERE singleton = 1",
            (int(ack[0]), int(reply_seq[0])),
        )
        provenance = raw.execute("SELECT * FROM channel_provenance").fetchone()
        reply_row = raw.execute(
            "SELECT * FROM channel_messages WHERE message_id = ?",
            (str(won.message_id),),
        ).fetchone()
        ack_row = raw.execute(
            "SELECT * FROM channel_acks WHERE message_id = ? AND actor_id = ?",
            (str(request.message_id), ADVISOR_ID),
        ).fetchone()
        assert provenance is not None and reply_row is not None and ack_row is not None
        _replace_test_only_channel_seal(
            raw,
            family=CHANNEL_PROVENANCE_FACT_FAMILY,
            selector="1",
            fact_hash=channel_provenance_fact_hash(provenance),
        )
        _replace_test_only_channel_seal(
            raw,
            family=CHANNEL_MESSAGE_FACT_FAMILY,
            selector=str(reply_row["message_seq"]),
            fact_hash=channel_message_fact_hash(reply_row),
        )
        _replace_test_only_channel_seal(
            raw,
            family=CHANNEL_ACK_FACT_FAMILY,
            selector=str(ack_row["ack_seq"]),
            fact_hash=channel_ack_fact_hash(ack_row, connection=raw),
        )
        raw.execute("DELETE FROM commands WHERE command_id = ?", (winner_id,))
        # This fixture deliberately projects a current winner back into the
        # opaque v6 era. Remove every v7-only positive command-phase proof as
        # well as its row; retaining them would describe deletion damage, not
        # honest historical opacity.
        raw.execute(
            "DELETE FROM durable_fact_seals"
            " WHERE fact_key = ?"
            " AND family IN ('command_claim', 'command_plan', 'command_terminal')",
            (winner_id,),
        )

    for _ in range(2):
        lost = await panel.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="legacy-loser",
        )
        assert isinstance(lost, ControlRejected)
        assert lost.faults[0].code is ControlCode.CHANNEL_ALREADY_REPLIED

    for _ in range(2):
        duplicate_ack = await panel.control.channels_ack(
            ADVISOR,
            message_id=request.message_id,
            idempotency_key="legacy-ack-loser",
        )
        assert isinstance(duplicate_ack, ControlRejected)
        assert duplicate_ack.faults[0].code is ControlCode.IDEMPOTENCY_CONFLICT


@pytest.mark.parametrize("preack", (False, True))
@pytest.mark.parametrize("projection", ("exact", "wake"))
async def test_a_null_reply_writer_cannot_downgrade_current_command_provenance(
    preack: bool,
    projection: str,
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(port=f"null-{preack}-{projection}"), ATTESTATION)
    if preack:
        acknowledged = await panel.control.channels_ack(
            ADVISOR,
            message_id=request.message_id,
            idempotency_key=f"null-preack-{projection}",
        )
        assert isinstance(acknowledged, ChannelAckResult)
    replied = await panel.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": 1},
        idempotency_key=f"null-reply-{preack}-{projection}",
    )
    assert isinstance(replied, ChannelReplyResult)
    with sqlite3.connect(panel.journal._db_path) as raw:
        row = raw.execute(
            "SELECT envelope_json FROM channel_messages WHERE message_id = ?",
            (str(replied.message_id),),
        ).fetchone()
        assert row is not None
        envelope = json.loads(row[0])
        envelope["payload"] = {"verdict": True}
        raw.execute(
            "UPDATE channel_messages SET command_id = NULL, envelope_json = ?"
            " WHERE message_id = ?",
            (canonical_json(json_value(envelope)), str(replied.message_id)),
        )

    with pytest.raises(JournalDamaged, match=r"not a valid durable fact|positive seal"):
        if projection == "exact":
            panel.channel.message(replied.message_id)
        else:
            panel.journal.answered_requests([request.message_id])


@pytest.mark.parametrize("projection", ("exact", "wake"))
async def test_an_opaque_v6_preack_cannot_hide_a_current_reply_writer(
    projection: str,
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """A legacy ack does not make a post-migration reply legacy."""

    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(port=f"opaque-preack-{projection}"), ATTESTATION)
    with sqlite3.connect(panel.journal._db_path) as raw:
        raw.row_factory = sqlite3.Row
        raw.execute(
            "INSERT INTO channel_acks (message_id, actor_id, command_id, acked_at,"
            " ack_provenance_version) VALUES (?, ?, ?, ?, 0)",
            (
                str(request.message_id),
                ADVISOR_ID,
                "cmd-v6-opaque-preack",
                clock.now().isoformat(),
            ),
        )
        ack_seq = int(raw.execute("SELECT MAX(ack_seq) FROM channel_acks").fetchone()[0])
        raw.execute(
            "UPDATE channel_provenance SET legacy_ack_through = ? WHERE singleton = 1",
            (ack_seq,),
        )
        provenance = raw.execute("SELECT * FROM channel_provenance").fetchone()
        ack_row = raw.execute(
            "SELECT * FROM channel_acks WHERE ack_seq = ?",
            (ack_seq,),
        ).fetchone()
        assert provenance is not None and ack_row is not None
        _replace_test_only_channel_seal(
            raw,
            family=CHANNEL_PROVENANCE_FACT_FAMILY,
            selector="1",
            fact_hash=channel_provenance_fact_hash(provenance),
        )
        seal_channel_ack(raw, ack_row)
    replied = await panel.control.channels_reply(
        ADVISOR,
        message_id=request.message_id,
        payload={"verdict": 1},
        idempotency_key=f"current-after-opaque-preack-{projection}",
    )
    assert isinstance(replied, ChannelReplyResult)
    for _ in range(2):
        duplicate = await panel.control.channels_ack(
            ADVISOR,
            message_id=request.message_id,
            idempotency_key=f"opaque-preack-loser-{projection}",
        )
        assert isinstance(duplicate, ControlRejected)
        assert duplicate.faults[0].code is ControlCode.IDEMPOTENCY_CONFLICT
    with sqlite3.connect(panel.journal._db_path) as raw:
        row = raw.execute(
            "SELECT envelope_json, reply_provenance_version FROM channel_messages"
            " WHERE message_id = ?",
            (str(replied.message_id),),
        ).fetchone()
        assert row is not None
        assert row[1] == 1
        envelope = json.loads(row[0])
        envelope["payload"] = {"verdict": True}
        raw.execute(
            "UPDATE channel_messages SET command_id = NULL, envelope_json = ?"
            " WHERE message_id = ?",
            (canonical_json(json_value(envelope)), str(replied.message_id)),
        )

    with pytest.raises(JournalDamaged, match=r"not a valid durable fact|positive seal"):
        if projection == "exact":
            panel.channel.message(replied.message_id)
        else:
            panel.journal.answered_requests([request.message_id])


async def test_a_duplicate_acknowledgement_replays_its_refusal(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(), ATTESTATION)
    first = await panel.control.channels_ack(
        ADVISOR,
        message_id=request.message_id,
        idempotency_key="ack-owner",
    )
    assert isinstance(first, ChannelAckResult)

    for _ in range(2):
        duplicate = await panel.control.channels_ack(
            ADVISOR,
            message_id=request.message_id,
            idempotency_key="ack-duplicate",
        )
        assert isinstance(duplicate, ControlRejected)
        assert duplicate.faults[0].code is ControlCode.IDEMPOTENCY_CONFLICT

    duplicate_id = command_id_for(ADVISOR_ID, "channels_ack", "ack-duplicate")
    with sqlite3.connect(panel.journal._db_path) as raw:
        row = raw.execute(
            "SELECT response_json FROM commands WHERE command_id = ?",
            (duplicate_id,),
        ).fetchone()
        assert row is not None
        response_json = str(row[0])
        response = json.loads(response_json)
        response["faults"][0]["repair"] = "forged repair"
        raw.execute(
            "UPDATE commands SET response_json = ? WHERE command_id = ?",
            (json.dumps(response, sort_keys=True, separators=(",", ":")), duplicate_id),
        )
    with pytest.raises(JournalDamaged, match=r"canonical response|positive seal"):
        await panel.control.channels_ack(
            ADVISOR,
            message_id=request.message_id,
            idempotency_key="ack-duplicate",
        )
    with sqlite3.connect(panel.journal._db_path) as raw:
        raw.execute(
            "UPDATE commands SET response_json = ? WHERE command_id = ?",
            (response_json, duplicate_id),
        )

    with sqlite3.connect(panel.journal._db_path) as raw:
        raw.execute(
            "DELETE FROM channel_acks WHERE message_id = ? AND actor_id = ?",
            (str(request.message_id), ADVISOR_ID),
        )
    with pytest.raises(
        JournalDamaged,
        match=r"foreign acknowledgement|append-only history|fact-seal inventory",
    ):
        await panel.control.channels_ack(
            ADVISOR,
            message_id=request.message_id,
            idempotency_key="ack-duplicate",
        )


@pytest.mark.parametrize("tamper", ["missing_writer", "unrelated_writer"])
async def test_ack_rejection_reproves_its_foreign_writer_plan(
    tamper: str,
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """A foreign ack row is not evidence without its exact authoring plan."""

    panel = _panel(tmp_path, clock, system)
    request = panel.channel.append_request(_intent(), ATTESTATION)
    owner = await panel.control.channels_ack(
        ADVISOR,
        message_id=request.message_id,
        idempotency_key="ack-proof-owner",
    )
    assert isinstance(owner, ChannelAckResult)
    duplicate = await panel.control.channels_ack(
        ADVISOR,
        message_id=request.message_id,
        idempotency_key="ack-proof-duplicate",
    )
    assert isinstance(duplicate, ControlRejected)

    forged_owner = "orphan:no-command"
    if tamper == "unrelated_writer":
        other = panel.channel.append_request(_intent(port="other"), ATTESTATION)
        planner = _panel(
            tmp_path,
            clock,
            system,
            _crash_at("channels_ack.after_plan"),
            "ack-proof-unrelated",
        )
        with pytest.raises(InjectedCrash):
            await planner.control.channels_ack(
                ADVISOR,
                message_id=other.message_id,
                idempotency_key="ack-proof-unrelated",
            )
        forged_owner = command_id_for(
            ADVISOR_ID,
            "channels_ack",
            "ack-proof-unrelated",
        )

    with sqlite3.connect(panel.journal._db_path) as raw:
        raw.execute(
            "UPDATE channel_acks SET command_id = ? WHERE message_id = ? AND actor_id = ?",
            (forged_owner, str(request.message_id), ADVISOR_ID),
        )

    with pytest.raises(
        JournalDamaged,
        match=r"acknowledgement|missing behind a dependent durable fact",
    ):
        await panel.control.channels_ack(
            ADVISOR,
            message_id=request.message_id,
            idempotency_key="ack-proof-duplicate",
        )
