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
    ControlCode,
    ControlRejected,
    command_id_for,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.human import (
    ADVICE_REPLY_CONTRACT,
    ADVICE_REQUEST_CONTRACT,
    AdviceReplyPayload,
)
from constructicon.core.identity import Digest, canonical_json, json_value
from constructicon.core.run import RunStatus
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.journal.sqlite import SqliteJournal
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


class _RecordingHost:
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
        self.control = ControlPlane(
            system=system,
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
    reply = panel.channel.reply(
        request_id=request.message_id,
        actor_id=ADVISOR_ID,
        payload={"verdict": "ship"},
        command_id="cmd-direct",
    )

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
    recovered = _panel(tmp_path, clock, system, None, "recovery")
    with pytest.raises(JournalDamaged, match="sealed request"):
        await recovered.control.channels_reply(
            ADVISOR,
            message_id=request.message_id,
            payload={"verdict": "ship"},
            idempotency_key="tamper",
        )
    assert recovered.channel.reply_for(request.message_id) is None


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


async def test_a_lost_race_past_preflight_is_typed_not_an_exception(
    tmp_path: Path,
    clock: FakeClock,
    system: Constructicon,
) -> None:
    """Two commands can both pass the already-replied check, then one loses.

    Preflight and the domain write are not one transaction, so the loser must
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
