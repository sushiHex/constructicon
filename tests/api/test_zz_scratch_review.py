"""Scratch review probes — DELETE ME."""

from __future__ import annotations

from typing import Any, cast

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.channel import ChannelSendIntent, request_message_id
from constructicon.core.control import (
    APPROVE_SCOPE,
    ApprovalCommandResult,
    AuthenticatedActor,
    ControlRejected,
)
from constructicon.core.effect import ComponentProofSubject
from constructicon.core.human import (
    APPROVAL_REPLY_CONTRACT,
    APPROVAL_REQUEST_CONTRACT,
    ApprovalRequestPayload,
)
from constructicon.core.identity import Digest, json_value
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import pipeline_graph

CHANNEL_ID = "channel/gate"
APPROVER_ID = "static:approver"
RUN = RunId("run-bound-approval")
PATH = ExecutionPath(scope=ScopePath(segments=("gate",)))
ATTESTATION = "att-bound-approval"

SUBJECT = ComponentProofSubject(
    component="test/triage",
    version=Digest("sha256:" + "a" * 64),
    baseline_version=None,
)

# An approver who holds approve and nothing else.
APPROVE_ONLY = AuthenticatedActor(
    actor_id=APPROVER_ID,
    auth_method="static",
    scopes=frozenset({APPROVE_SCOPE}),
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


def _intent(port: str = "gate") -> ChannelSendIntent:
    return ChannelSendIntent(
        message_id=request_message_id(
            run_id=RUN,
            path=PATH,
            channel_id=CHANNEL_ID,
            channel_revision="1",
            lane="gate",
            interaction="approval",
            port=port,
        ),
        channel_id=CHANNEL_ID,
        channel_revision="1",
        lane="gate",
        interaction="approval",
        recipient_actor_id=APPROVER_ID,
        contract=APPROVAL_REQUEST_CONTRACT,
        reply_contract=APPROVAL_REPLY_CONTRACT,
        run_id=RUN,
        path=PATH,
        port=port,
        reply_port=f"{port}-decision",
        payload=ApprovalRequestPayload(
            subject=json_value(SUBJECT.model_dump(mode="json")),
        ).model_dump(mode="json"),
    )


def _plane(world: Constructicon, journal: SqliteJournal) -> tuple[ControlPlane, MailboxChannel]:
    if journal.run_record(RUN) is None:
        inputs = {"issue": {"title": "gate"}}
        world._prepare_run(world.validate(pipeline_graph(), inputs), run_id=RUN, inputs=inputs)
    host = _RecordingHost()
    plane = ControlPlane(
        system=world,
        store=journal,
        run_host=cast(RunHost, host),
        owner_id="scratch",
        command_ttl_s=30,
    )
    return plane, MailboxChannel(journal, channel_id=CHANNEL_ID)


async def test_probe_unbound_approve_without_read(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    plane, _ = _plane(world, journal)
    result = await plane.runs_approve(
        APPROVE_ONLY,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="probe-unbound",
    )
    print("UNBOUND RESULT:", type(result), result)
    assert isinstance(result, (ApprovalCommandResult, ControlRejected))


async def test_probe_bound_approve_without_read(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    plane, channel = _plane(world, journal)
    request = channel.append_request(_intent(), ATTESTATION)
    result = await plane.runs_approve(
        APPROVE_ONLY,
        run_id=RUN,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="probe-bound",
        request_message_id=request.message_id,
    )
    print("BOUND RESULT:", type(result), result)
    stored_reply = channel.reply_for(request.message_id)
    print("STORED REPLY:", stored_reply.message_id if stored_reply else None)
    assert isinstance(result, (ApprovalCommandResult, ControlRejected))
