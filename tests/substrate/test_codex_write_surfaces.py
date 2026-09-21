"""One whole-outcome rule covers successful and refused callback exchanges."""

import asyncio
import json

import pytest

from constructicon.core.executor import TaskSpec
from constructicon.substrate.executors.codex import CodexConversation
from constructicon.substrate.executors.codex_protocol import (
    CONTAINED_PYTHON_CATALOG,
    decode_turn,
    unavailable_outcome,
)
from tests.substrate.test_codex_adapter import EXPECTED, FINISHED
from tests.substrate.test_codex_protocol import assert_published_surfaces_are_bounded
from tests.substrate.test_codex_write import WRITE_GRANTS, write_native


@pytest.mark.parametrize("accept", [True, False])
async def test_callback_and_account_frames_do_not_escape_any_public_outcome_field(accept):
    program = "print('private-program-marker')"
    native = write_native(program=program)
    for reply in native.accounts:
        reply["result"] = {
            **reply["result"],
            "account": {**reply["result"]["account"], "email": "account-marker@example.invalid"},
        }
    if not accept:
        native.accounts[-1]["result"]["account"]["type"] = "apiKey"
    calls = []

    async def worker(source):
        calls.append(source)
        return "private-worker-response-marker"

    conversation = CodexConversation(
        task=TaskSpec(instruction="bounded WRITE"), grants=WRITE_GRANTS, expected=EXPECTED,
        input_limit=1024 * 1024, catalog=CONTAINED_PYTHON_CATALOG,
        worker=worker, deadline=asyncio.get_running_loop().time() + 5,
    )
    await asyncio.wait_for(conversation(native), 5)
    if conversation.faults:
        outcome = unavailable_outcome(
            conversation.faults, conversation.observation, FINISHED,
            requested_model=WRITE_GRANTS.model_selection.model,
        )
    else:
        outcome = decode_turn(
            conversation.observation, FINISHED,
            requested_model=WRITE_GRANTS.model_selection.model,
        )
    assert calls == [program] and len(native.callback_responses) == 1
    assert outcome.status == ("success" if accept else "failure")
    assert_published_surfaces_are_bounded(outcome)
    public = json.dumps(outcome.model_dump(mode="json"))
    for marker in (
        "private-program-marker", "private-worker-response-marker", "account-marker",
    ):
        assert marker not in public
    if not accept:
        assert outcome.output is None and outcome.raw_reply is None
