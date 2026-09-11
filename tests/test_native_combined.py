"""Portable assertion tests; native qualification runs separately on Linux."""

from copy import deepcopy

import pytest

from tests.native_codex_probe import PROBE_PROMPT
from tests.native_combined import BASE_INSTRUCTIONS, CombinedScenario, message, tools_for
from tests.native_provider import provider_peer
from tests.native_startup import MODELS
from tests.test_native_provider import address as address
from tests.test_native_provider import request_bytes, transact


@pytest.fixture(params=MODELS)
def scenario(request):
    return CombinedScenario(request.param, ("2026-09-11",), "contained_python",
                            {"program": "inert"}, '{"contained": true}')


def request_for(scenario, ordinal):
    items = scenario.prefix(scenario.dates[0]) + (scenario.suffix() if ordinal == 2 else [])
    request = {"model": scenario.model,
               "input": [{"id": f"item_{index}", **item} for index, item in enumerate(items)]}
    if scenario.model == MODELS[0]:
        request.update(instructions=BASE_INSTRUCTIONS, tools=tools_for())
    return request


@pytest.mark.parametrize("ordinal", [1, 2])
def test_exact_conversation_has_a_positive_control(scenario, ordinal):
    scenario(request_for(scenario, ordinal), ordinal)


@pytest.mark.parametrize("damage", [
    "earlier-user", "extra-developer", "extra-environment", "changed-context", "stale-date",
    "duplicate-prompt", "missing-prompt", "unrecognized-field", "missing-id", "flattened",
    "changed-tool-schema", "foreign-output", "changed-output", "changed-call", "third-request",
])
def test_conversation_refuses_uncontrolled_context_and_outputs(scenario, damage):
    request = request_for(scenario, 2)
    inputs = request["input"]
    if damage in {"earlier-user", "extra-developer", "extra-environment"}:
        item = (message("user", "different") if damage == "earlier-user" else
                message("developer", "different") if damage == "extra-developer" else
                deepcopy(inputs[-4]))
        inputs.insert(0, {"id": "extra", **item})
    elif damage == "changed-context":
        inputs[-4]["content"][0]["text"] += "uncontrolled"
    elif damage == "stale-date":
        inputs[-4]["content"][0]["text"] = inputs[-4]["content"][0]["text"].replace(
            "2026-09-11", "2025-01-01",
        )
    elif damage == "duplicate-prompt":
        inputs.insert(-2, deepcopy(inputs[-3]))
    elif damage == "missing-prompt":
        del inputs[-3]
    elif damage == "unrecognized-field":
        inputs[-3]["instructions"] = "different"
    elif damage == "missing-id":
        del inputs[-3]["id"]
    elif damage == "flattened":
        if scenario.model == MODELS[0]:
            del request["instructions"]
        else:
            request["tools"] = tools_for()
    elif damage == "changed-tool-schema":
        tools = request["tools"] if scenario.model == MODELS[0] else inputs[0]["tools"][0]["tools"]
        tools[-1]["parameters"]["additionalProperties"] = True
    elif damage == "foreign-output":
        inputs[-1]["call_id"] = "other"
    elif damage == "changed-output":
        inputs[-1]["output"] = "invented"
    elif damage == "changed-call":
        inputs[-2]["arguments"] = '{}'
    with pytest.raises(ValueError):
        scenario(request, 3 if damage == "third-request" else 2)


async def test_endpoint_applies_full_check_before_sending_the_fixed_script(address, scenario):
    request = request_for(scenario, 1)
    request["input"].insert(-1, {"id": "earlier", **message("user", "different")})
    async with provider_peer(model=scenario.model, path=address,
                             request_check=scenario, scenario=PROBE_PROMPT) as peer:
        assert await transact(peer, request_bytes(request)) == b""
    assert len(peer.requests) == 1
    assert any("unexpected native context" in error for error in peer.failures)


async def test_exact_bytes_do_not_authenticate_a_native_sender(address, scenario):
    # This portable client is NOT Codex. Matching bytes establish no authorship.
    async with provider_peer(model=scenario.model, path=address,
                             request_check=scenario, scenario=PROBE_PROMPT) as peer:
        response = await transact(peer, request_bytes(request_for(scenario, 1)))
    assert b"200 OK" in response and not peer.failures
