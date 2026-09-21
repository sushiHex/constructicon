"""N2's Linux lane: the pinned binary refuses a credential-free session.

Two things answer requests here and must not be conflated. The **pinned binary
itself** answers the JSON-RPC surface, including ``account/read``, from its own
auth state. The fixture peer in ``tests/native_provider.py`` answers only the
model HTTP requests behind it. So this is a client to a real codex, composed
through the accepted placement fixture: a Unix socket peer, the contained
bridge, and the bootstrap that execs ``codex app-server --strict-config
--stdio``.

The launch belongs to the fixture's own ``exchange``, so what runs here is the
same standalone ``CodexConversation`` the provider's ``execute`` drives — its
second consumer, over the same ``ProcessIO`` contract, with its own framing
rather than the fixture's test-side wire.

Two facts about a composed byte scope are handled through the conversation's
ordinary parameters rather than a test-only wrapper. The fixture writes its own
setup record through the handle before this query runs, spending cumulative
input budget, so the conversation is given a deliberately small allowance
instead of the launcher's whole one. The bootstrap then announces itself in two
records on the same stream, so the conversation is given a preamble count to
drain before ``initialize``.

**What this proves is refusal, and that is the honest result.** The lane is
credential-free, so ``account/read`` returns a null account, the pre-turn gate
refuses, no turn is sent, and the outcome is an unavailable failure naming the
faults. Acceptance is unprovable here and belongs to N4, where a binding is
established with the operator present; the cross-platform tests cover the
accepting path against scripted replies.

The default fixture provider sets ``requires_openai_auth = false``, and at the
pin the account state is empty *precisely when* that flag is false — so the pair
of faults in the first case is one configuration fact observed twice, not two
independent findings, and it is not evidence that the store is empty. The exact
pair is still asserted: it will break loudly when N3 flips the flag, which is
the right failure. The second case supplies ``requires_openai_auth = true`` and
is the store-empty proof.
"""

import json
import re

import pytest

from constructicon.core.executor import TaskSpec
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.substrate.executors.codex import CodexConversation
from constructicon.substrate.executors.codex_protocol import (
    NO_ACCOUNT_FAULT,
    PROVIDER_OVERRIDE_FAULT,
    ExpectedAccount,
    unavailable_outcome,
)
from tests.native_codex_probe import TOOL
from tests.native_startup import MODELS, configuration
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_startup import assert_outcome
from tests.substrate.test_provider_placement import observe, placement
from tests.substrate.test_provider_placement import placement_image as placement_image

INSTRUCTION = "Return the inert placement fixture response."
EXPECTED = ExpectedAccount(plan_type="pro")
BOOTSTRAP_RECORDS = 2
"""The placement record and the bootstrap record, both before the app-server."""

INPUT_BYTES = 64 * 1024
"""Far below the launcher's 1 MiB cumulative allowance, because the fixture's
setup record already spent part of it. This conversation sends a handful of
small records and must never assume the whole budget survived."""

GRANTS = EffectiveGrants(
    posture=Posture.READ,
    model_selection=ModelSelection(kind="explicit", model=MODELS[0]),
    effort="low",
    allowed_tools=(),
    env_allowlist=(),
    network="allow",
    timeout_s=600,
)


def refusal_query(held):
    async def query(wire, observed):
        conversation = CodexConversation(
            task=TaskSpec(instruction=INSTRUCTION), grants=GRANTS, expected=EXPECTED,
            input_limit=INPUT_BYTES, preamble=BOOTSTRAP_RECORDS,
        )
        held.append(conversation)
        await conversation(wire.io)
        placement_record, bootstrap = conversation.preamble_records
        observed["placement"] = json.loads(placement_record)["placement"]
        observed["bootstrap"] = json.loads(bootstrap)
        observed["codex_faults"] = list(conversation.faults)
        observed["codex_transcript"] = conversation.observation.raw
        # New information about the pinned interface: which notifications the
        # app-server emits before a turn exists. Recorded rather than asserted,
        # because this lane is the only place it is observable.
        observed["codex_withheld_methods"] = list(conversation.withheld_methods)

    return query


async def refuse(image, guard_root, *, config=None):
    held = []
    async with placement(image, model=MODELS[0]) as (composed, peer, record):
        observations, result = await observe(
            composed, peer, guard_root, record=record, query=refusal_query(held), config=config,
        )
    assert_outcome(result)
    assert held, "the adapter conversation never ran"
    conversation = held[0]
    assert len(conversation.preamble_records) == BOOTSTRAP_RECORDS
    # The bootstrap's own records belong to the fixture and are retained
    # separately; they never reach the transcript and are not counted as withheld.
    for record in conversation.preamble_records:
        assert record.decode() not in conversation.observation.raw
    # What *is* in the transcript is the withheld-record marker, and nothing else.
    # The pinned app-server emits notifications before the gate refuses — a fact
    # about the vendor this lane is the only place to observe, so the count is
    # pinned rather than erased, and the methods are recorded as evidence.
    assert re.fullmatch(r"\[\d+ records withheld from this turn\]",
                        conversation.observation.raw), conversation.observation.raw
    assert conversation.withheld_methods, "the marker implies at least one record"
    # No turn was sent, so the model peer behind the bridge was never reached.
    assert not peer.requests
    assert not conversation.observation.terminal
    outcome = unavailable_outcome(
        conversation.faults, conversation.observation, result,
        requested_model=GRANTS.model_selection.model,
    )
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert outcome.error.produced_output is False
    assert outcome.output is None and outcome.raw_reply is None
    return conversation, observations, outcome


async def test_the_pinned_binary_refuses_a_credential_free_session(placement_image, tmp_path):
    conversation, observations, outcome = await refuse(placement_image, tmp_path)
    assert conversation.faults == (NO_ACCOUNT_FAULT, PROVIDER_OVERRIDE_FAULT)
    assert NO_ACCOUNT_FAULT in outcome.error.detail
    assert PROVIDER_OVERRIDE_FAULT in outcome.error.detail
    assert observations["codex_faults"] == list(conversation.faults)
    assert observations["bootstrap"]["absent"]


async def test_a_provider_requiring_openai_auth_leaves_only_the_empty_store_fault(
    placement_image, tmp_path,
):
    config = configuration(MODELS[0]).replace(
        "requires_openai_auth = false", "requires_openai_auth = true",
    )
    assert "requires_openai_auth = true" in config
    conversation, _observations, outcome = await refuse(
        placement_image, tmp_path, config=config,
    )
    assert conversation.faults == (NO_ACCOUNT_FAULT,)
    assert outcome.error.detail == NO_ACCOUNT_FAULT


@pytest.mark.parametrize("experimental_api", [False, True])
async def test_pinned_dynamic_tool_registration_requires_explicit_opt_in(
    placement_image, tmp_path, experimental_api,
):
    """Protocol availability only: no turn, account, credential or model call.

    Both cases send identical registration bytes. Only this connection's
    initialization capability differs. The fixture's private configuration
    selects its inert provider; the request cannot select a model or route.
    """
    async def register(wire, observed):
        observed["placement"] = (await wire.read())["placement"]
        observed["bootstrap"] = await wire.read()
        observed["initialize"] = await wire.rpc("initialize", {
            "clientInfo": {"name": "constructicon_callback_gate", "version": "0"},
            "capabilities": {"experimentalApi": True} if experimental_api else {},
        })
        await wire.send({"method": "initialized"})
        wire.sequence += 1
        request_id = wire.sequence
        await wire.send({"id": request_id, "method": "thread/start", "params": {
            "cwd": "/tmp/native-startup", "sandbox": "read-only", "ephemeral": True,
            "dynamicTools": [TOOL],
        }})
        while True:
            reply = await wire.read()
            if "id" not in reply and "method" in reply:
                continue  # Wire enforces cumulative and per-record bounds.
            assert type(reply.get("id")) is int and reply["id"] == request_id
            assert "method" not in reply
            observed["registration"] = reply
            break
        await wire.io.close_stdin()

    async with placement(placement_image) as (composed, peer, record):
        observations, result = await observe(
            composed, peer, tmp_path, record=record, query=register,
        )
    assert_outcome(result)
    assert peer.requests == [], "registration must not start a model turn"
    registration = observations["registration"]
    if experimental_api:
        assert "error" not in registration
        thread_id = registration["result"]["thread"]["id"]
        assert isinstance(thread_id, str) and thread_id
    else:
        assert "result" not in registration
        error = registration["error"]
        assert error["code"] == -32600
        assert error["message"] == (
            "thread/start.dynamicTools requires experimentalApi capability"
        )
