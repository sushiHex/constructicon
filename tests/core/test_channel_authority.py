"""One authorization law for every channel surface (M7 PR C).

A reply carries no recipient of its own — it is addressed to the run, not to a
person — so authority is never read off the message actually addressed. It
comes from the request that reply answers, validated in full, so summary,
detail, reply, and ack cannot drift into separate interpretations.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.channel import (
    ChannelContract,
    ChannelSendIntent,
    governing_request,
    message_for_intent,
    message_for_reply,
    request_message_id,
)
from constructicon.core.control import ADVISE_SCOPE, APPROVE_SCOPE, INTERACTION_SCOPES
from constructicon.core.errors import JournalDamaged

RUN = RunId("run-authority")
PATH = ExecutionPath(scope=ScopePath(segments=("review",)))
RECIPIENT = "static:advisor"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
REQUEST_CONTRACT = ChannelContract(type_id="test/Ask", schema_hash="ask-v1")
REPLY_CONTRACT = ChannelContract(type_id="test/Answer", schema_hash="answer-v1")


def _request(interaction: str = "advice", port: str = "request"):
    intent = ChannelSendIntent(
        message_id=request_message_id(
            run_id=RUN,
            path=PATH,
            channel_id="channel/review",
            channel_revision="1",
            lane="review",
            interaction=interaction,
            port=port,
        ),
        channel_id="channel/review",
        channel_revision="1",
        lane="review",
        interaction=interaction,
        recipient_actor_id=RECIPIENT,
        contract=REQUEST_CONTRACT,
        reply_contract=REPLY_CONTRACT,
        run_id=RUN,
        path=PATH,
        port=port,
        reply_port="answer",
        payload={"question": "ship?"},
    )
    return message_for_intent(intent, created_at=NOW)


def _reply(request):
    return message_for_reply(
        request,
        actor_id=RECIPIENT,
        payload={"verdict": "ship"},
        created_at=NOW,
    )


def test_a_request_governs_itself() -> None:
    request = _request()
    assert governing_request(request, None) is request


def test_a_replys_authority_comes_from_the_request_it_answers() -> None:
    """The reply's own recipient is None by construction, so it cannot govern."""

    request = _request()
    reply = _reply(request)
    assert reply.recipient_actor_id is None

    governing = governing_request(reply, request)
    assert governing is request
    assert governing.recipient_actor_id == RECIPIENT
    assert governing.interaction == "advice"


@pytest.mark.parametrize(
    ("interaction", "scope"),
    [("advice", ADVISE_SCOPE), ("approval", APPROVE_SCOPE)],
)
def test_the_required_scope_follows_the_sealed_interaction(
    interaction: str,
    scope: str,
) -> None:
    """Advising is not approving, and the request says which this is."""

    request = _request(interaction=interaction)
    reply = _reply(request)
    for message, governing in ((request, request), (reply, request)):
        resolved = governing_request(message, governing)
        assert INTERACTION_SCOPES[resolved.interaction] == scope


def test_a_reply_without_its_request_is_damage() -> None:
    with pytest.raises(JournalDamaged, match="names no stored request"):
        governing_request(_reply(_request()), None)


def test_a_reply_governed_by_the_wrong_request_is_damage() -> None:
    """Authority may not be borrowed from a request the reply does not answer."""

    reply = _reply(_request())
    other = _request(port="second-request")
    with pytest.raises(JournalDamaged, match="does not answer request"):
        governing_request(reply, other)


def test_an_approval_reply_cannot_be_governed_by_an_advice_request() -> None:
    """Otherwise an approval could be answered under advise scope."""

    approval = _request(interaction="approval")
    reply = _reply(approval)
    advice = _request(interaction="advice")
    with pytest.raises(JournalDamaged):
        governing_request(reply, advice)
    assert INTERACTION_SCOPES[governing_request(reply, approval).interaction] == APPROVE_SCOPE
