"""MCP carries the channel surface without acquiring any of its authority (M7).

A handler derives one actor from the transport, delegates once, and returns the
domain result. It never opens a store, interprets a cursor, chooses a lane, or
computes an identity — so the scope matrices below are proofs about the control
plane, reached through the transport that will actually be used.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from mcp import Client

from constructicon.api.control import ControlPlane
from constructicon.api.mcp import StaticActorSource, create_mcp_server
from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.channel import (
    ChannelInteraction,
    ChannelSendIntent,
    request_message_id,
)
from constructicon.core.control import (
    ADVISE_SCOPE,
    APPROVE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    ControlCode,
)
from constructicon.core.effect import ComponentProofSubject
from constructicon.core.human import (
    ADVICE_REPLY_CONTRACT,
    ADVICE_REQUEST_CONTRACT,
    APPROVAL_REPLY_CONTRACT,
    APPROVAL_REQUEST_CONTRACT,
    ApprovalRequestPayload,
)
from constructicon.core.identity import Digest, json_value
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.journal.sqlite import SqliteJournal

SERVER = Path(__file__).parents[3] / "src" / "constructicon" / "api" / "mcp" / "server.py"
CHANNEL_TOOLS = ("channels_inbox", "channels_message", "channels_reply", "channels_ack")

CHANNEL_ID = "channel/mcp"
ADVISOR_ID = "static:mcp-advisor"
APPROVER_ID = "static:mcp-approver"
READER_ID = "static:mcp-reader"
RUN = RunId("run-mcp-channels")
PATH = ExecutionPath(scope=ScopePath(segments=("review",)))
ATTESTATION = "att-mcp-channels"
SUBJECT = ComponentProofSubject(
    component="test/triage",
    version=Digest("sha256:" + "c" * 64),
    baseline_version=None,
)


def _actor(actor_id: str, *scopes: str) -> AuthenticatedActor:
    return AuthenticatedActor(
        actor_id=actor_id,
        auth_method="static",
        scopes=frozenset(scopes),
    )


ADVISOR = _actor(ADVISOR_ID, READ_SCOPE, ADVISE_SCOPE)
APPROVER = _actor(APPROVER_ID, READ_SCOPE, APPROVE_SCOPE)
READER = _actor(READER_ID, READ_SCOPE)


def _handlers() -> dict[str, ast.AsyncFunctionDef]:
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    found: dict[str, ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in CHANNEL_TOOLS:
            found[node.name] = node
    return found


def test_every_channel_handler_delegates_exactly_once() -> None:
    """One statement, one call, and the call is the same operation by name.

    A handler that grew a second statement would be growing control-plane
    semantics inside a transport, where no other transport could inherit them.
    """

    handlers = _handlers()
    assert set(handlers) == set(CHANNEL_TOOLS)
    for name, handler in handlers.items():
        assert len(handler.body) == 1, name
        statement = handler.body[0]
        assert isinstance(statement, ast.Return), name
        call = statement.value
        if isinstance(call, ast.Await):
            call = call.value
        assert isinstance(call, ast.Call), name
        assert isinstance(call.func, ast.Attribute), name
        assert call.func.attr == name, name
        assert isinstance(call.func.value, ast.Name), name
        assert call.func.value.id == "control", name


def test_no_channel_handler_takes_an_actor_or_a_routing_argument() -> None:
    """The caller supplies a message and an answer. Never who, where, or which."""

    for name, handler in _handlers().items():
        arguments = {argument.arg for argument in handler.args.args}
        arguments |= {argument.arg for argument in handler.args.kwonlyargs}
        assert not arguments & {
            "actor",
            "actor_id",
            "recipient_actor_id",
            "channel_id",
            "lane",
            "interaction",
            "run_id",
            "path",
            "reply_port",
            "reply_id",
            "contract",
            "revision",
        }, name


def test_the_transport_holds_no_channel_law() -> None:
    """Identity, paging, routing, and storage all stay behind the facade."""

    source = SERVER.read_text(encoding="utf-8")
    for forbidden in (
        "request_message_id(",
        "reply_message_id(",
        "CursorCodec",
        "ChannelRevision",
        "ActorInboxRevision",
        "MailboxChannel",
        "channel_actor_inbox",
        "channel_reply(",
        "INTERACTION_SCOPES",
        "governing_request",
        "authorized_delivery",
    ):
        assert forbidden not in source, forbidden


def _intent(
    *,
    port: str,
    recipient: str,
    interaction: ChannelInteraction,
) -> ChannelSendIntent:
    """One request typed by the canonical contracts for its own interaction."""

    request_contract, reply_contract = (
        (APPROVAL_REQUEST_CONTRACT, APPROVAL_REPLY_CONTRACT)
        if interaction == "approval"
        else (ADVICE_REQUEST_CONTRACT, ADVICE_REPLY_CONTRACT)
    )
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
        contract=request_contract,
        reply_contract=reply_contract,
        run_id=RUN,
        path=PATH,
        port=port,
        reply_port=f"{port}-answer",
        payload=ApprovalRequestPayload(
            subject=json_value(SUBJECT.model_dump(mode="json")),
        ).model_dump(mode="json"),
    )


def _server(
    world: Constructicon,
    journal: SqliteJournal,
    actor: AuthenticatedActor,
) -> Any:
    return create_mcp_server(
        ControlPlane(system=world, store=journal),
        StaticActorSource(actor),
    )


def _fault(result: Any) -> str:
    assert result.is_error is False
    payload = result.structured_content
    assert isinstance(payload, dict)
    body = payload.get("result", payload)
    assert isinstance(body, dict)
    return str(body["faults"][0]["code"])


async def test_the_channel_scope_matrix_holds_through_the_transport(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """Advise, approve, and read are three independent authorities.

    Each actor reaches the same tools; what differs is only what the sealed
    request lets it do. The transport contributes nothing to that.
    """

    channel = MailboxChannel(journal, channel_id=CHANNEL_ID)
    advice = channel.append_request(
        _intent(port="advice", recipient=ADVISOR_ID, interaction="advice"),
        ATTESTATION,
    )
    approval = channel.append_request(
        _intent(port="gate", recipient=APPROVER_ID, interaction="approval"),
        ATTESTATION,
    )

    # An advisor sees its own row and answers it; the approval is not its work.
    async with Client(_server(world, journal, ADVISOR), raise_exceptions=True) as client:
        page = _structured(await client.call_tool("channels_inbox", {}))
        assert [item["message_id"] for item in page["items"]] == [str(advice.message_id)]
        replied = _structured(
            await client.call_tool(
                "channels_reply",
                {
                    "message_id": str(advice.message_id),
                    "payload": {"verdict": "ship"},
                    "idempotency_key": "mcp-advice",
                },
            )
        )
        assert replied["request_id"] == str(advice.message_id)
        assert (
            _fault(
                await client.call_tool("channels_message", {"message_id": str(approval.message_id)})
            )
            == ControlCode.AUTH_REQUIRED_SCOPE.value
        )

    # An approver may not use the advice path even for its own request.
    async with Client(_server(world, journal, APPROVER), raise_exceptions=True) as client:
        page = _structured(await client.call_tool("channels_inbox", {}))
        assert [item["message_id"] for item in page["items"]] == [str(approval.message_id)]
        assert (
            _fault(
                await client.call_tool(
                    "channels_reply",
                    {
                        "message_id": str(approval.message_id),
                        "payload": {"decision": "approved"},
                        "idempotency_key": "mcp-wrong-path",
                    },
                )
            )
            == ControlCode.CHANNEL_WRONG_INTERACTION.value
        )
        acked = _structured(
            await client.call_tool(
                "channels_ack",
                {
                    "message_id": str(approval.message_id),
                    "idempotency_key": "mcp-ack",
                },
            )
        )
        assert acked["actor_id"] == APPROVER_ID

    # Read alone opens the run surface and none of the channel surface.
    async with Client(_server(world, journal, READER), raise_exceptions=True) as client:
        assert _fault(await client.call_tool("channels_inbox", {})) == (
            ControlCode.AUTH_REQUIRED_SCOPE.value
        )
        assert (
            _fault(
                await client.call_tool(
                    "channels_ack",
                    {
                        "message_id": str(advice.message_id),
                        "idempotency_key": "mcp-reader-ack",
                    },
                )
            )
            == ControlCode.AUTH_REQUIRED_SCOPE.value
        )
        listed = _structured(await client.call_tool("runs_list", {}))
        assert listed["page"]["count"] == 0


def _structured(result: Any) -> dict[str, Any]:
    assert result.is_error is False
    payload = result.structured_content
    assert isinstance(payload, dict)
    wrapped = payload.get("result")
    if len(payload) == 1 and isinstance(wrapped, dict):
        return wrapped
    return payload
