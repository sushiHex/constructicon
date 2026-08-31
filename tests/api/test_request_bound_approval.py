"""A decision that is also an answer (M7 PR C).

Bound to a request, `runs_approve` writes three facts — the `ApprovalRecord`,
the reply the run is waiting on, and the request's acknowledgement — in one
commit. Unbound, it is byte-for-byte the M6 operation it has always been.
"""

from __future__ import annotations

import sqlite3
from typing import Any, cast

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.channel import (
    ChannelContract,
    ChannelSendIntent,
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
    command_id_for,
)
from constructicon.core.effect import ApprovalRecord, ComponentProofSubject
from constructicon.core.errors import JournalDamaged
from constructicon.core.human import (
    APPROVAL_REPLY_CONTRACT,
    APPROVAL_REQUEST_CONTRACT,
    ApprovalDecisionPayload,
    ApprovalRequestPayload,
    approval_decision_payload,
)
from constructicon.core.identity import Digest, canonical_json, json_value
from constructicon.core.run import RunStatus
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.journal.sqlite import SqliteJournal
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


class _RecordingHost:
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

    with pytest.raises(JournalDamaged, match="acknowledgement"):
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

    # Written straight to the transport: a well-formed decision naming a record
    # that was never stored, so only the third fact is missing.
    gate.channel.reply(
        request_id=request.message_id,
        actor_id=APPROVER_ID,
        payload={
            "schema_version": 1,
            "approval": {
                "approval_id": "approval-never-stored",
                "subject": SUBJECT.model_dump(mode="json"),
                "decision": "approved",
                "reason": None,
                "actor": APPROVER.model_dump(mode="json"),
                "run_id": str(RUN),
                "created_at": "2026-01-01T00:00:00+00:00",
            },
        },
        command_id="cmd-no-approval",
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
    elsewhere = await _standalone("standalone-elsewhere")
    record = journal.approval(carried.approval_id)
    assert record is not None

    # 1. The reply's command wrote no approval at all.
    first = gate.channel.append_request(_intent(port="splice-a"), ATTESTATION)
    gate.channel.reply(
        request_id=first.message_id,
        actor_id=APPROVER_ID,
        payload={"schema_version": 1, "approval": record.model_dump(mode="json")},
        command_id="cmd-wrote-no-approval",
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
    second = gate.channel.append_request(_intent(port="splice-b"), ATTESTATION)
    gate.channel.reply(
        request_id=second.message_id,
        actor_id=APPROVER_ID,
        payload={"schema_version": 1, "approval": record.model_dump(mode="json")},
        command_id=command_id_for(APPROVER_ID, "runs_approve", "standalone-elsewhere"),
    )
    assert elsewhere.approval_id != carried.approval_id
    with pytest.raises(JournalDamaged, match="its own command did not write"):
        await gate.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="after-splice-b",
            request_message_id=second.message_id,
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
    gate.channel.reply(
        request_id=request_id,
        actor_id=sender,
        payload={"schema_version": 1, "approval": record.model_dump(mode="json")},
        command_id=command_id,
    )


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

    # 1. The record decides a different run.
    wrong_run, wrong_run_command = await _standalone_approval(
        gate, run_id=other_run, subject=SUBJECT, key="agree-run"
    )
    first = gate.channel.append_request(_intent(port="agree-run"), ATTESTATION)
    _splice(gate, first.message_id, wrong_run, wrong_run_command, APPROVER_ID)
    with pytest.raises(JournalDamaged, match="run, actor, or subject"):
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
    wrong_subject, wrong_subject_command = await _standalone_approval(
        gate, run_id=RUN, subject=SUBJECT, key="agree-subject"
    )
    second = gate.channel.append_request(
        _intent(port="agree-subject", subject=OTHER_SUBJECT), ATTESTATION
    )
    _splice(gate, second.message_id, wrong_subject, wrong_subject_command, APPROVER_ID)
    with pytest.raises(JournalDamaged, match="run, actor, or subject"):
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
    stranger = AuthenticatedActor(
        actor_id="static:other-approver",
        auth_method="static",
        scopes=frozenset({READ_SCOPE, APPROVE_SCOPE}),
    )
    wrong_actor, wrong_actor_command = await _standalone_approval(
        gate, run_id=RUN, subject=SUBJECT, key="agree-actor"
    )
    third = gate.channel.append_request(
        _intent(port="agree-actor").model_copy(update={"recipient_actor_id": None}),
        ATTESTATION,
    )
    _splice(gate, third.message_id, wrong_actor, wrong_actor_command, stranger.actor_id)
    with pytest.raises(JournalDamaged, match="run, actor, or subject"):
        await gate.control.runs_approve(
            APPROVER,
            run_id=RUN,
            subject=SUBJECT,
            decision="approved",
            reason=None,
            idempotency_key="after-agree-actor",
            request_message_id=third.message_id,
        )
