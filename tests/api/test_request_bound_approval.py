"""A decision that is also an answer (M7 PR C).

Bound to a request, `runs_approve` writes three facts — the `ApprovalRecord`,
the reply the run is waiting on, and the request's acknowledgement — in one
commit. Unbound, it is byte-for-byte the M6 operation it has always been.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, cast

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.channel import (
    ChannelAck,
    ChannelAckRecord,
    ChannelContract,
    ChannelSendIntent,
    message_for_reply,
    reply_message_id,
    request_message_id,
)
from constructicon.core.control import (
    ADVISE_SCOPE,
    APPROVE_SCOPE,
    READ_SCOPE,
    ApprovalCommandResult,
    AuthenticatedActor,
    ControlCode,
    ControlRejected,
    approval_id_for_command,
    command_id_for,
    command_request_hash,
)
from constructicon.core.effect import ApprovalRecord, ComponentProofSubject
from constructicon.core.errors import JournalDamaged
from constructicon.core.human import (
    APPROVAL_REPLY_CONTRACT,
    APPROVAL_REQUEST_CONTRACT,
    ApprovalDecisionPayload,
    ApprovalRequestPayload,
    ChannelApprovalPlan,
    StoredApprovalPlan,
    approval_decision_payload,
)
from constructicon.core.identity import Digest, canonical_json, json_value
from constructicon.core.run import RunStatus
from constructicon.substrate.journal._sqlite_approvals import seal_approval
from constructicon.substrate.journal._sqlite_channels import (
    CHANNEL_ACK_FACT_FAMILY,
    _channel_ack_fact_key,
    _insert_message,
    channel_ack_fact_hash,
    seal_channel_message,
)
from constructicon.substrate.journal._sqlite_fact_seals import store_durable_fact_seal
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.channel_requests import AttestedMailboxChannel as MailboxChannel
from tests.conftest import FakeClock, InjectedCrash, pipeline_graph

CHANNEL_ID = "channel/gate"
APPROVER_ID = "static:approver"
RUN = RunId("run-bound-approval")
PATH = ExecutionPath(scope=ScopePath(segments=("gate",)))
ATTESTATION = "att-bound-approval"
SEAMS = ("after_plan", "after_domain_mutation", "after_command_completion")

SUBJECT = ComponentProofSubject(
    component="test/triage",
    version=Digest("sha256:" + "a" * 64),
    baseline_version=None,
)
OTHER_SUBJECT = ComponentProofSubject(
    component="test/triage",
    version=Digest("sha256:" + "b" * 64),
    baseline_version=None,
)

APPROVER = AuthenticatedActor(
    actor_id=APPROVER_ID,
    auth_method="static",
    scopes=frozenset({READ_SCOPE, APPROVE_SCOPE}),
)
ADVISOR = AuthenticatedActor(
    actor_id=APPROVER_ID,
    auth_method="static",
    scopes=frozenset({READ_SCOPE, ADVISE_SCOPE}),
)


class _RecordingHost(RunHost):
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
    port: str = "gate",
    subject: ComponentProofSubject = SUBJECT,
    contract: ChannelContract = APPROVAL_REQUEST_CONTRACT,
    reply_contract: ChannelContract = APPROVAL_REPLY_CONTRACT,
    interaction: str = "approval",
) -> ChannelSendIntent:
    return ChannelSendIntent(
        message_id=request_message_id(
            run_id=RUN,
            path=PATH,
            channel_id=CHANNEL_ID,
            channel_revision="1",
            lane="gate",
            interaction=interaction,  # type: ignore[arg-type]
            port=port,
        ),
        channel_id=CHANNEL_ID,
        channel_revision="1",
        lane="gate",
        interaction=interaction,  # type: ignore[arg-type]
        recipient_actor_id=APPROVER_ID,
        contract=contract,
        reply_contract=reply_contract,
        run_id=RUN,
        path=PATH,
        port=port,
        reply_port=f"{port}-decision",
        payload=ApprovalRequestPayload(
            subject=json_value(subject.model_dump(mode="json")),
        ).model_dump(mode="json"),
    )


class _Gate:
    """One control plane over the run the bound request is waiting on."""

    def __init__(
        self,
        world: Constructicon,
        journal: SqliteJournal,
        probe: Any,
        owner: str,
    ) -> None:
        self.journal = journal
        self.host = _RecordingHost()
        self.host._system = world
        self.host._journal = journal
        self.channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
        self.control = ControlPlane(
            system=world,
            store=journal,
            run_host=cast(RunHost, self.host),
            owner_id=owner,
            command_ttl_s=30,
            fault_probe=probe,
        )


def _gate(
    world: Constructicon,
    journal: SqliteJournal,
    probe: Any = None,
    owner: str = "bound-approval",
) -> _Gate:
    if journal.run_record(RUN) is None:
        inputs = {"issue": {"title": "gate"}}
        world._prepare_run(world.validate(pipeline_graph(), inputs), run_id=RUN, inputs=inputs)
    return _Gate(world, journal, probe, owner)


def _crash_at(target: str) -> Any:
    def crash(name: str) -> None:
        if name == target:
            raise InjectedCrash(name)

    return crash


async def test_a_bound_decision_writes_all_three_facts(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """One decision in three places: the record, the answer, the delivery fact."""

    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(), ATTESTATION)

    result = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason="looks right",
        idempotency_key="bound-1",
        request_message_id=request.message_id,
    )
    assert isinstance(result, ApprovalCommandResult)
    assert result.reply == reply_message_id(
        request_id=request.message_id,
        reply_port="gate-decision",
    )

    approval = gate.journal.approval(result.approval_id)
    assert approval is not None and approval.subject == SUBJECT

    reply = gate.channel.reply_for(request.message_id)
    assert reply is not None
    assert reply.message_id == result.reply
    assert reply.sender_actor_id == APPROVER_ID
    assert reply.contract == APPROVAL_REPLY_CONTRACT

    # The answer a run reads is the trusted record itself, so a component can
    # return a governance fact rather than a rumour about one.
    carried = ApprovalDecisionPayload.model_validate(reply.envelope.payload).approval
    assert carried == approval
    assert carried.actor == APPROVER
    assert carried.subject == SUBJECT
    assert carried.approval_id == result.approval_id

    delivery = gate.journal.channel_delivery(
        message_id=request.message_id,
        actor_id=APPROVER_ID,
    )
    assert delivery is not None and delivery.acknowledged

    run_id, kwargs = gate.host.launches[0]
    assert run_id == RUN
    assert kwargs["allowed_statuses"] == frozenset({RunStatus.PARKED})
    assert kwargs["cause"].id == str(result.reply)


async def test_wake_projection_requires_the_approval_positive_seal(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """A bound reply cannot wake from an approval exact reads reject."""

    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(port="sealed-wake"), ATTESTATION)
    result = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="sealed-wake",
        request_message_id=request.message_id,
    )
    assert isinstance(result, ApprovalCommandResult)
    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "DELETE FROM durable_fact_seals"
            " WHERE family = 'approval' AND fact_key = ?",
            (result.approval_id,),
        )

    with pytest.raises(JournalDamaged, match="positive seal"):
        journal.answered_requests([request.message_id])


async def test_a_later_ack_command_recognizes_the_approval_plan_owner(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(port="approval-owned-ack"), ATTESTATION)
    decided = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="approval-owned-ack-decision",
        request_message_id=request.message_id,
    )
    assert isinstance(decided, ApprovalCommandResult)

    first = await gate.control.channels_ack(
        APPROVER,
        message_id=request.message_id,
        idempotency_key="approval-owned-ack-loser",
    )
    assert isinstance(first, ControlRejected)
    assert first.faults[0].code is ControlCode.IDEMPOTENCY_CONFLICT

    replayed = await gate.control.channels_ack(
        APPROVER,
        message_id=request.message_id,
        idempotency_key="approval-owned-ack-loser",
    )
    assert replayed == first


async def test_a_rejected_decision_is_ordinary_data(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """Nothing branches on which way the human decided; both wake identically."""

    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(), ATTESTATION)

    result = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="rejected",
        reason="not yet",
        idempotency_key="bound-reject",
        request_message_id=request.message_id,
    )
    assert isinstance(result, ApprovalCommandResult)
    assert result.decision == "rejected"
    reply = gate.channel.reply_for(request.message_id)
    assert reply is not None
    carried = ApprovalDecisionPayload.model_validate(reply.envelope.payload).approval
    assert carried.decision == "rejected"
    assert len(gate.host.launches) == 1
    assert gate.host.launches[0][1]["cause"].id == str(result.reply)


async def test_an_unbound_decision_keeps_its_m6_bytes_exactly(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """The additive field is absent, not null, in request, plan, and response.

    Hashing `request_message_id: null` into a standalone decision would change
    every command id already recorded under an existing idempotency key.
    """

    gate = _gate(world, journal)
    result = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="legacy",
    )
    assert isinstance(result, ApprovalCommandResult)
    assert result.reply is None
    assert "reply" not in result.model_dump(mode="json")

    command = gate.journal.command(
        command_id_for(APPROVER_ID, "runs_approve", "legacy"),
    )
    assert command is not None
    assert isinstance(command.request, dict)
    assert "request_message_id" not in command.request
    assert isinstance(command.plan, dict)
    assert command.plan["plan"]["kind"] == "approval"  # type: ignore[index,call-overload]
    assert isinstance(command.response, dict)
    assert "reply" not in command.response


async def test_a_decision_refuses_a_subject_its_request_did_not_pin(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """Compared as canonical bytes, and refused before any command exists."""

    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(), ATTESTATION)

    refused = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=OTHER_SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="wrong-subject",
        request_message_id=request.message_id,
    )
    assert isinstance(refused, ControlRejected)
    assert refused.faults[0].code is ControlCode.APPROVAL_INVALID_SUBJECT
    assert gate.journal.latest_command_key(operation="runs_approve") is None
    assert gate.channel.reply_for(request.message_id) is None

    # The key was never burned, so the correct decision still uses it.
    accepted = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="wrong-subject",
        request_message_id=request.message_id,
    )
    assert isinstance(accepted, ApprovalCommandResult)


async def test_a_decision_refuses_an_exchange_that_is_not_a_human_approval(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """An ApprovalRecord may not be written into a lookalike conversation."""

    gate = _gate(world, journal)
    impostor = gate.channel.append_request(
        _intent(
            port="lookalike",
            contract=ChannelContract(type_id="other/Ask", schema_hash="ask-1"),
        ),
        ATTESTATION,
    )

    refused = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="impostor",
        request_message_id=impostor.message_id,
    )
    assert isinstance(refused, ControlRejected)
    assert refused.faults[0].code is ControlCode.APPROVAL_INVALID_SUBJECT
    assert gate.journal.latest_command_key(operation="runs_approve") is None


async def test_a_decision_refuses_an_advice_request(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """Request-bound approval is the mirror of `channels_reply`, not a superset."""

    gate = _gate(world, journal)
    advice = gate.channel.append_request(_intent(interaction="advice"), ATTESTATION)

    refused = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="advice-bound",
        request_message_id=advice.message_id,
    )
    assert isinstance(refused, ControlRejected)
    assert refused.faults[0].code is ControlCode.CHANNEL_WRONG_INTERACTION
    assert gate.journal.latest_command_key(operation="runs_approve") is None


async def test_a_second_command_after_a_recorded_decision_is_typed(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(), ATTESTATION)
    first = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="race-first",
        request_message_id=request.message_id,
    )
    assert isinstance(first, ApprovalCommandResult)

    late = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="rejected",
        reason=None,
        idempotency_key="race-second",
        request_message_id=request.message_id,
    )
    assert isinstance(late, ControlRejected)
    assert late.faults[0].code is ControlCode.CHANNEL_ALREADY_REPLIED


async def test_a_torn_decision_is_damage_not_a_lost_race(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """A reply whose request its own sender never acked cannot have committed."""

    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(), ATTESTATION)
    first = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="torn-first",
        request_message_id=request.message_id,
    )
    assert isinstance(first, ApprovalCommandResult)

    # Tear the triple behind the control plane's back.
    with sqlite3.connect(journal._db_path) as raw:
        raw.execute("DELETE FROM channel_acks WHERE message_id = ?", (str(request.message_id),))

    with pytest.raises(
        JournalDamaged,
        match=r"acknowledgement|fact-seal inventory",
    ):
        await gate.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="torn-second",
            request_message_id=request.message_id,
        )


@pytest.mark.parametrize("seam", SEAMS)
async def test_a_bound_decision_survives_every_response_loss_seam(
    seam: str,
    world: Constructicon,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    """One commit, so recovery finds all three facts or none, never a half."""

    crashing = _gate(world, journal, _crash_at(f"runs_approve.{seam}"), "crash")
    request = crashing.channel.append_request(_intent(), ATTESTATION)
    with pytest.raises(InjectedCrash):
        await crashing.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason="seam",
            idempotency_key="seam",
            request_message_id=request.message_id,
        )

    clock.advance(31)
    recovered = _gate(world, journal, None, "recovery")
    result = await recovered.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason="seam",
        idempotency_key="seam",
        request_message_id=request.message_id,
    )
    assert isinstance(result, ApprovalCommandResult)
    assert result.command.replayed is (seam == "after_command_completion")

    reply = recovered.channel.reply_for(request.message_id)
    assert reply is not None and reply.message_id == result.reply
    stored = recovered.journal.approval(result.approval_id)
    assert stored is not None
    assert canonical_json(json_value(reply.envelope.payload)) == canonical_json(
        approval_decision_payload(stored)
    )
    delivery = recovered.journal.channel_delivery(
        message_id=request.message_id,
        actor_id=APPROVER_ID,
    )
    assert delivery is not None and delivery.acknowledged


@pytest.mark.parametrize("owner", ["approval", "reply"])
async def test_terminal_bound_replay_requires_both_facts_to_belong_to_its_command(
    owner: str,
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """Matching bytes are not provenance for a trusted governance fact."""

    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(), ATTESTATION)
    result = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason="owned",
        idempotency_key="terminal-owner",
        request_message_id=request.message_id,
    )
    assert isinstance(result, ApprovalCommandResult)
    assert result.reply is not None

    with sqlite3.connect(journal._db_path) as raw:
        if owner == "approval":
            raw.execute(
                "UPDATE approvals SET command_id = ? WHERE approval_id = ?",
                ("cmd-forged-owner", result.approval_id),
            )
        else:
            raw.execute(
                "UPDATE channel_messages SET command_id = ? WHERE message_id = ?",
                ("cmd-forged-owner", str(result.reply)),
            )

    with pytest.raises(JournalDamaged):
        await gate.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason="owned",
            idempotency_key="terminal-owner",
            request_message_id=request.message_id,
        )


async def test_an_advisor_may_not_decide_an_approval(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(), ATTESTATION)

    refused = await gate.control.runs_approve(
        ADVISOR,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="advisor",
        request_message_id=request.message_id,
    )
    assert isinstance(refused, ControlRejected)
    assert refused.faults[0].code is ControlCode.AUTH_REQUIRED_SCOPE
    assert gate.channel.reply_for(request.message_id) is None


OTHER_RUN = RunId("run-bound-approval-other")


def _second_run(world: Constructicon, journal: SqliteJournal) -> RunId:
    """A second real run, so the refusal is about authority and not existence."""

    if journal.run_record(OTHER_RUN) is None:
        inputs = {"issue": {"title": "other"}}
        world._prepare_run(
            world.validate(pipeline_graph(), inputs),
            run_id=OTHER_RUN,
            inputs=inputs,
        )
    return OTHER_RUN


async def test_a_decision_refuses_a_request_belonging_to_another_run(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """A record claiming one run while its reply wakes another decides nothing.

    Both runs exist, so this is not a liveness check: the command names a run,
    the request belongs to a run, and nothing but this makes them the same one.
    """

    gate = _gate(world, journal)
    other = _second_run(world, journal)
    request = gate.channel.append_request(_intent(), ATTESTATION)

    refused = await gate.control.runs_approve(
        APPROVER,
        run_id=other,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="cross-run",
        request_message_id=request.message_id,
    )
    assert isinstance(refused, ControlRejected)
    assert refused.faults[0].code is ControlCode.APPROVAL_RUN_MISMATCH
    assert refused.faults[0].details == {"run_id": str(RUN)}

    # No command, no approval, no reply, no acknowledgement.
    assert journal.latest_command_key(operation="runs_approve") is None
    with sqlite3.connect(journal._db_path) as raw:
        assert raw.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
    assert gate.channel.reply_for(request.message_id) is None
    delivery = journal.channel_delivery(message_id=request.message_id, actor_id=APPROVER_ID)
    assert delivery is not None and not delivery.acknowledged

    # The key was never burned, so the correct run still uses it.
    accepted = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="cross-run",
        request_message_id=request.message_id,
    )
    assert isinstance(accepted, ApprovalCommandResult)
    carried = ApprovalDecisionPayload.model_validate(
        gate.channel.reply_for(request.message_id).envelope.payload  # type: ignore[union-attr]
    ).approval
    assert carried.run_id == RUN


async def test_a_reply_and_ack_without_an_approval_record_is_damage(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """Two of the three facts is not a race this command lost.

    Approval, reply, and acknowledgement commit together, so an exchange
    carrying only the channel halves cannot have come from a decision. Reached
    from the reply: its sender names the acknowledgement, and the
    acknowledgement names the command that must also have written the approval.
    """

    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(), ATTESTATION)

    writer_key = "torn-triple-writer"
    crashing = _gate(
        world,
        journal,
        _crash_at("runs_approve.after_plan"),
        "torn-triple-writer",
    )
    with pytest.raises(InjectedCrash):
        await crashing.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key=writer_key,
            request_message_id=request.message_id,
        )
    command_id = command_id_for(APPROVER_ID, "runs_approve", writer_key)
    writer = journal.command(command_id)
    assert writer is not None
    stored = StoredApprovalPlan.model_validate(writer.plan)
    assert isinstance(stored.plan, ChannelApprovalPlan)

    # Injected below the now-guarded public transport: a well-formed decision
    # naming a record that was never stored, so only the third fact is missing.
    _force_impossible_approval_reply(
        gate,
        request_id=request.message_id,
        sender=APPROVER_ID,
        payload=cast(dict[str, Any], stored.plan.payload),
        command_id=command_id,
    )

    with pytest.raises(JournalDamaged, match="without the approval"):
        await gate.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="torn-triple",
            request_message_id=request.message_id,
        )


async def test_acknowledging_first_does_not_forfeit_the_right_to_decide(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """An explicit ack keeps its own command; the decision only implies delivery.

    Reaching the approval record through the acknowledgement's owning command
    would call this legitimate sequence damage, because that command wrote an
    acknowledgement and no approval.
    """

    gate = _gate(world, journal)
    request = gate.channel.append_request(_intent(), ATTESTATION)

    acked = await gate.control.channels_ack(
        APPROVER,
        message_id=request.message_id,
        idempotency_key="ack-before-deciding",
    )
    assert not isinstance(acked, ControlRejected)

    decided = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="decide-after-ack",
        request_message_id=request.message_id,
    )
    assert isinstance(decided, ApprovalCommandResult)

    # And a later command still reads the completed exchange as a lost race.
    late = await gate.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="decide-late",
        request_message_id=request.message_id,
    )
    assert isinstance(late, ControlRejected)
    assert late.faults[0].code is ControlCode.CHANNEL_ALREADY_REPLIED


async def test_a_late_decision_loser_plans_before_it_observes_and_reproves_the_winner(
    world: Constructicon,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    """An extant decision does not replace the losing command's domain plan."""

    winner = _gate(world, journal, None, "winner")
    request = winner.channel.append_request(_intent(), ATTESTATION)
    won = await winner.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="rejected",
        reason="mine",
        idempotency_key="late-winner",
        request_message_id=request.message_id,
    )
    assert isinstance(won, ApprovalCommandResult)

    crashing = _gate(
        world,
        journal,
        _crash_at("runs_approve.after_plan"),
        "late-loser",
    )
    with pytest.raises(InjectedCrash):
        await crashing.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="late-loser",
            request_message_id=request.message_id,
        )

    loser_id = command_id_for(APPROVER_ID, "runs_approve", "late-loser")
    winner_id = command_id_for(APPROVER_ID, "runs_approve", "late-winner")
    with sqlite3.connect(journal._db_path) as raw:
        row = raw.execute(
            "SELECT plan_json FROM commands WHERE command_id = ?",
            (loser_id,),
        ).fetchone()
        assert row is not None
        assert json.loads(row[0])["plan"]["kind"] == "channel_approval"
        # The reply alone cannot prove the atomic approval exchange. Tearing the
        # winner before replay must surface damage, not repeat a stale refusal.
        raw.execute(
            "DELETE FROM approvals WHERE command_id = ?",
            (winner_id,),
        )

    clock.advance(31)
    recovered = _gate(world, journal, None, "late-loser-recovery")
    with pytest.raises(JournalDamaged, match="without the approval"):
        await recovered.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="late-loser",
            request_message_id=request.message_id,
        )


async def test_a_bound_plan_cannot_be_downgraded_to_a_standalone_approval(
    world: Constructicon,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    """The request key's presence is immutable, including across response loss."""

    crashing = _gate(world, journal, _crash_at("runs_approve.after_plan"), "downgrade")
    request = crashing.channel.append_request(_intent(port="downgrade"), ATTESTATION)
    key = "downgrade-bound-approval"
    with pytest.raises(InjectedCrash):
        await crashing.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key=key,
            request_message_id=request.message_id,
        )

    command_id = command_id_for(APPROVER_ID, "runs_approve", key)
    with sqlite3.connect(journal._db_path) as raw:
        row = raw.execute(
            "SELECT plan_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None
        stored = json.loads(row[0])
        assert stored["plan"]["kind"] == "channel_approval"
        stored["plan"] = {
            "kind": "approval",
            "approval": stored["plan"]["approval"],
        }
        raw.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (json.dumps(stored), command_id),
        )

    clock.advance(31)
    recovered = _gate(world, journal, None, "downgrade-recovery")
    with pytest.raises(
        JournalDamaged,
        match=r"approval plan contradicts|positive seal",
    ):
        await recovered.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key=key,
            request_message_id=request.message_id,
        )

    assert journal.approval_for_command(command_id) is None
    assert recovered.channel.reply_for(request.message_id) is None
    delivery = journal.channel_delivery(
        message_id=request.message_id,
        actor_id=APPROVER_ID,
    )
    assert delivery is not None and not delivery.acknowledged


async def test_a_lost_decision_replays_its_refusal(
    world: Constructicon,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    """A refusal a domain plan lawfully emitted must repeat, not become damage."""

    crashing = _gate(world, journal, _crash_at("runs_approve.after_plan"), "crash")
    request = crashing.channel.append_request(_intent(), ATTESTATION)
    with pytest.raises(InjectedCrash):
        await crashing.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="loser",
            request_message_id=request.message_id,
        )

    winner = _gate(world, journal, None, "winner")
    won = await winner.control.runs_approve(
        APPROVER,
        run_id=RUN,
        subject=SUBJECT,
        decision="rejected",
        reason="mine",
        idempotency_key="winner",
        request_message_id=request.message_id,
    )
    assert isinstance(won, ApprovalCommandResult)

    clock.advance(31)
    resumed = _gate(world, journal, None, "resumed")
    for _ in range(2):
        lost = await resumed.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="loser",
            request_message_id=request.message_id,
        )
        assert isinstance(lost, ControlRejected)
        assert lost.faults[0].code is ControlCode.CHANNEL_ALREADY_REPLIED

    loser_id = command_id_for(APPROVER_ID, "runs_approve", "loser")
    with sqlite3.connect(journal._db_path) as raw:
        row = raw.execute(
            "SELECT response_json FROM commands WHERE command_id = ?",
            (loser_id,),
        ).fetchone()
        assert row is not None
        response_json = str(row[0])
        forged = response_json.replace(
            "already carries its one decision",
            "carries a forged decision",
        )
        assert forged != response_json
        raw.execute(
            "UPDATE commands SET response_json = ? WHERE command_id = ?",
            (forged, loser_id),
        )
    with pytest.raises(JournalDamaged, match=r"canonical response|positive seal"):
        await resumed.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="loser",
            request_message_id=request.message_id,
        )
    with sqlite3.connect(journal._db_path) as raw:
        raw.execute(
            "UPDATE commands SET response_json = ? WHERE command_id = ?",
            (response_json, loser_id),
        )

    # A terminal refusal remains relational: if the immutable winning triple is
    # torn later, replay reports damage rather than repeating a fact no longer true.
    with sqlite3.connect(journal._db_path) as raw:
        raw.execute(
            "DELETE FROM approvals WHERE command_id = ?",
            (command_id_for(APPROVER_ID, "runs_approve", "winner"),),
        )
    with pytest.raises(JournalDamaged, match="without the approval"):
        await resumed.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="loser",
            request_message_id=request.message_id,
        )


async def test_a_standalone_approval_spliced_into_an_exchange_is_damage(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """Existence is not togetherness, in either direction.

    A real `ApprovalRecord` carried inside a reply is not a complete foreign
    transaction. The reply names the command that wrote it, and that command
    must be the one that wrote *this* approval — whether it wrote none at all,
    or wrote a different one.
    """

    gate = _gate(world, journal)

    async def _standalone(key: str) -> ApprovalCommandResult:
        result = await gate.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=key,
            idempotency_key=key,
        )
        assert isinstance(result, ApprovalCommandResult)
        return result

    carried = await _standalone("standalone-carried")
    record = journal.approval(carried.approval_id)
    assert record is not None

    # Prepare both lawful requests before either impossible exchange is
    # injected. Once damage exists, opening a helper journal must fail closed.
    first = gate.channel.append_request(_intent(port="splice-a"), ATTESTATION)
    second = gate.channel.append_request(_intent(port="splice-b"), ATTESTATION)

    # 1. The reply's command wrote no approval at all.
    _force_bound_approval_exchange(
        gate,
        request_id=first.message_id,
        subject=SUBJECT,
        run_id=RUN,
        key="splice-wrote-no-approval",
        store_approval=False,
    )
    with pytest.raises(JournalDamaged, match="without the approval record"):
        await gate.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="after-splice-a",
            request_message_id=first.message_id,
        )

    # 2. The reply's command wrote an approval, but not the one carried.
    own = _force_bound_approval_exchange(
        gate,
        request_id=second.message_id,
        subject=SUBJECT,
        run_id=RUN,
        key="splice-wrote-another-approval",
        reply_approval=record,
    )
    assert own.approval_id != carried.approval_id
    with pytest.raises(
        JournalDamaged,
        match=r"its own command did not write|plan contradicts its channel reply",
    ):
        await gate.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="after-splice-b",
            request_message_id=second.message_id,
        )


async def test_an_exact_standalone_approval_still_is_not_one_atomic_exchange(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """Matching run, actor, subject, and bytes cannot replace the writer's plan."""

    gate = _gate(world, journal)
    record, writer = await _standalone_approval(
        gate,
        run_id=RUN,
        subject=SUBJECT,
        key="exact-standalone",
    )
    request = gate.channel.append_request(_intent(port="exact-splice"), ATTESTATION)
    _splice(gate, request.message_id, record, writer, APPROVER_ID)

    with pytest.raises(JournalDamaged, match="request-bound approval plan"):
        await gate.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="rejected",
            reason=None,
            idempotency_key="after-exact-splice",
            request_message_id=request.message_id,
        )


async def _standalone_approval(
    gate: _Gate,
    *,
    run_id: RunId,
    subject: ComponentProofSubject,
    key: str,
    actor: AuthenticatedActor = APPROVER,
) -> tuple[ApprovalRecord, str]:
    """One real standalone decision, plus the command id that wrote it."""

    result = await gate.control.runs_approve(
        actor,
        run_id=run_id,
        subject=subject,
        decision="approved",
        reason=None,
        idempotency_key=key,
    )
    assert isinstance(result, ApprovalCommandResult)
    record = gate.journal.approval(result.approval_id)
    assert record is not None
    return record, command_id_for(actor.actor_id, "runs_approve", key)


def _splice(
    gate: _Gate,
    request_id: Digest,
    record: ApprovalRecord,
    command_id: str,
    sender: str,
) -> None:
    _force_impossible_approval_reply(
        gate,
        request_id=request_id,
        sender=sender,
        payload={"schema_version": 1, "approval": record.model_dump(mode="json")},
        command_id=command_id,
    )


def _force_impossible_approval_reply(
    gate: _Gate,
    *,
    request_id: Digest,
    sender: str,
    payload: dict[str, Any],
    command_id: str,
) -> None:
    """Inject impossible history below the public approval-reply guard."""

    request = gate.channel.message(request_id)
    assert request is not None
    observed_at = gate.journal._now()
    reply = message_for_reply(
        request,
        actor_id=sender,
        payload=payload,
        created_at=observed_at,
    )
    with gate.journal._txn() as connection:
        _insert_message(connection, reply, None, command_id)
        connection.execute(
            "INSERT INTO channel_acks (message_id, actor_id, command_id, acked_at,"
            " ack_provenance_version) VALUES (?, ?, ?, ?, 1)",
            (
                str(request_id),
                sender,
                command_id,
                observed_at.isoformat(),
            ),
        )
        reply_row = connection.execute(
            "SELECT * FROM channel_messages WHERE message_id = ?",
            (str(reply.message_id),),
        ).fetchone()
        ack_row = connection.execute(
            "SELECT * FROM channel_acks WHERE message_id = ? AND actor_id = ?",
            (str(request_id), sender),
        ).fetchone()
        assert reply_row is not None and ack_row is not None
        seal_channel_message(connection, reply_row)
        # Test-only impossible history: the acknowledgement is individually
        # exact and current, while the deliberately incomplete approval triple
        # cannot pass the production exchange projector used by seal_channel_ack.
        record = ChannelAckRecord(
            ack=ChannelAck(
                message_id=request_id,
                actor_id=sender,
                acked_at=observed_at,
            ),
            command_id=command_id,
            provenance_version=1,
        )
        store_durable_fact_seal(
            connection,
            family=CHANNEL_ACK_FACT_FAMILY,
            fact_key=_channel_ack_fact_key(record),
            selector=str(ack_row["ack_seq"]),
            fact_hash=channel_ack_fact_hash(
                ack_row,
                record=record,
                connection=connection,
            ),
        )


def _force_bound_approval_exchange(
    gate: _Gate,
    *,
    request_id: Digest,
    subject: ComponentProofSubject,
    run_id: RunId,
    key: str,
    sender: str = APPROVER_ID,
    store_approval: bool = True,
    reply_approval: ApprovalRecord | None = None,
) -> ApprovalRecord:
    """Write internally coherent command evidence below only the tested relation."""

    request = gate.channel.message(request_id)
    assert request is not None
    assert request.reply_port is not None
    command_request = {
        "run_id": str(run_id),
        "subject": json_value(subject.model_dump(mode="json")),
        "decision": "approved",
        "reason": None,
        "request_message_id": str(request_id),
    }
    claimed = gate.journal.claim_command(
        actor=APPROVER,
        operation="runs_approve",
        idempotency_key=key,
        request_hash=command_request_hash(command_request),
        request=command_request,
        owner_id="test:impossible-bound-approval",
        ttl_s=30,
    )
    assert claimed.claim is not None
    command_id = claimed.claim.command_id
    approval = ApprovalRecord(
        approval_id=approval_id_for_command(
            command_id,
            json_value(subject.model_dump(mode="json")),
        ),
        subject=subject,
        decision="approved",
        reason=None,
        actor=APPROVER,
        run_id=run_id,
        created_at=gate.journal._now(),
    )
    reply_id = reply_message_id(
        request_id=request.message_id,
        reply_port=request.reply_port,
    )
    plan = ChannelApprovalPlan(
        approval=approval,
        channel_id=request.channel_id,
        request_id=request.message_id,
        reply_id=reply_id,
        reply_port=request.reply_port,
        payload=approval_decision_payload(approval),
        ack_actor_id=APPROVER_ID,
        run_id=run_id,
        parked_event_seq=gate.journal.max_event_seq(request.envelope.run_id),
    )
    gate.journal.store_command_plan(
        claimed.claim,
        StoredApprovalPlan(plan=plan).model_dump(mode="json"),
    )
    if store_approval:
        with gate.journal._txn() as connection:
            connection.execute(
                "INSERT INTO approvals (approval_id, run_id, subject_json, decision,"
                " reason, actor_json, command_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    approval.approval_id,
                    str(approval.run_id),
                    canonical_json(json_value(approval.subject.model_dump(mode="json"))),
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
            # This explicitly test-only impossible-history builder bypasses the
            # atomic writer. Keep every fact outside the relation under test
            # truthful, including the v7 positive approval proof.
            seal_approval(connection, row)
    _force_impossible_approval_reply(
        gate,
        request_id=request_id,
        sender=sender,
        payload=cast(
            dict[str, Any],
            approval_decision_payload(reply_approval or approval),
        ),
        command_id=command_id,
    )
    return approval


async def test_the_three_facts_must_agree_on_run_actor_and_subject(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """Provenance is necessary, not sufficient.

    Each case below has a real approval written by the very command that wrote
    the reply carrying it — so the provenance link holds — and still describes a
    decision this exchange did not make.
    """

    gate = _gate(world, journal)
    other_run = _second_run(world, journal)
    stranger = AuthenticatedActor(
        actor_id="static:other-approver",
        auth_method="static",
        scopes=frozenset({READ_SCOPE, APPROVE_SCOPE}),
    )

    # Admit all three requests before injecting any impossible history. The
    # attestation helper opens the same database, and a damaged journal must
    # never reopen merely so a later subcase can be arranged.
    first = gate.channel.append_request(_intent(port="agree-run"), ATTESTATION)
    second = gate.channel.append_request(
        _intent(port="agree-subject", subject=OTHER_SUBJECT), ATTESTATION
    )
    third = gate.channel.append_request(
        _intent(port="agree-actor").model_copy(update={"recipient_actor_id": None}),
        ATTESTATION,
    )

    # 1. The record decides a different run.
    _force_bound_approval_exchange(
        gate,
        request_id=first.message_id,
        subject=SUBJECT,
        run_id=other_run,
        key="agree-run",
    )
    with pytest.raises(
        JournalDamaged,
        match=r"sealed request|run, actor, or subject",
    ):
        await gate.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="after-agree-run",
            request_message_id=first.message_id,
        )

    # 2. The record decides a different subject.
    _force_bound_approval_exchange(
        gate,
        request_id=second.message_id,
        subject=SUBJECT,
        run_id=RUN,
        key="agree-subject",
    )
    with pytest.raises(
        JournalDamaged,
        match=r"sealed request|run, actor, or subject",
    ):
        await gate.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=OTHER_SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="after-agree-subject",
            request_message_id=second.message_id,
        )

    # 3. The record names a different decider than the reply's sender. An open
    #    request is the only one a second actor may answer, so it is the only
    #    place this disagreement can arise at all.
    _force_bound_approval_exchange(
        gate,
        request_id=third.message_id,
        subject=SUBJECT,
        run_id=RUN,
        key="agree-actor",
        sender=stranger.actor_id,
    )
    with pytest.raises(
        JournalDamaged,
        match=r"sealed request|run, actor, or subject",
    ):
        await gate.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="after-agree-actor",
            request_message_id=third.message_id,
        )
