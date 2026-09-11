"""Portable assertion tests; native qualification runs separately on Linux."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.native_codex_probe import PROBE_PROMPT
from tests.native_combined import (
    BASE_INSTRUCTIONS,
    CombinedScenario,
    canonical,
    fixed_request_fields,
    message,
    tools_for,
)
from tests.native_provider import provider_peer
from tests.native_startup import MODELS
from tests.test_native_provider import address as address
from tests.test_native_provider import request_bytes, transact


@pytest.mark.parametrize("name,expected", [
    ("native_combined_tools.json",
     "5c4eb4222231029c8481fb5d0275ce9e6439ee73ff0bdb4446ae7de381645aa5"),
    ("native_combined_sol_tools.json",
     "2af69894c7d1da46180c29ab5b0a6d996e6daad08d7f1a93d9f6de217a2a10b1"),
])
def test_previously_observed_tool_goldens_are_pinned(name, expected):
    value = json.loads(Path(__file__).with_name("fixtures").joinpath(name).read_text())
    assert hashlib.sha256(canonical(value).encode()).hexdigest() == expected


@pytest.fixture(params=MODELS)
def scenario(request):
    return CombinedScenario(request.param, ("2026-09-11",), "contained_python",
                            {"program": "inert"}, '{"contained": true}')


def request_for(scenario, ordinal):
    items = scenario.prefix(scenario.dates[0]) + (scenario.suffix() if ordinal == 2 else [])
    request = {**fixed_request_fields(scenario.model),
               "client_metadata": {}, "prompt_cache_key": "test",
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
    "previous-response", "foreign-conversation", "unknown-root", "generation-setting",
    "changed-instructions",
])
def test_conversation_refuses_uncontrolled_context_and_outputs(scenario, damage):
    request = request_for(scenario, 1 if damage == "third-request" else 2)
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
    elif damage in {"previous-response", "foreign-conversation", "unknown-root"}:
        request[{
            "previous-response": "previous_response_id", "foreign-conversation": "conversation",
            "unknown-root": "arbitrary_context",
        }[damage]] = "foreign"
    elif damage == "generation-setting":
        request["store"] = True
    elif damage == "changed-instructions":
        if scenario.model == MODELS[0]:
            request["instructions"] = "different"
        else:
            inputs[1]["content"][0]["text"] = "different"
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


async def test_failed_worker_keeps_complete_evidence_before_refusal():
    from constructicon.core.executor import ExecutorError, ExecutorFailure
    from tests.substrate.test_native_combined import worker_result

    result = ExecutorFailure(raw_reply="partial bytes", error=ExecutorError(
        kind="exit", detail="fixture refused", exit_code=3, produced_output=True,
    ))

    async def execute(*_args, **_kwargs):
        return result

    resource = SimpleNamespace(execute=execute,
                               context=SimpleNamespace(binding=SimpleNamespace(effective_grants={})))
    observations = []
    with pytest.raises(AssertionError):
        await worker_result(resource, object(), "inert", observations)
    assert observations == [result.model_dump(mode="json")]


@pytest.mark.parametrize("elapsed", ["0", "0.2", "19.9"])
def test_positive_patch_control_excludes_only_bounded_elapsed_text(scenario, elapsed):
    from dataclasses import replace

    scenario = replace(scenario, tool="apply_patch", arguments={"patch": "inert"}, restricted=False,
                       output="Exit code: 0\nWall time: <elapsed> seconds\nOutput:\nfixture\n")
    request = request_for(scenario, 2)
    if scenario.model == MODELS[0]:
        request["tools"] = tools_for(restricted=False)
    request["input"][-1]["output"] = scenario.output.replace("<elapsed>", elapsed)
    scenario(request, 2)
    for wrong in ("21", "nan", "-1", "0 seconds\nuncontrolled\nWall time: 0"):
        request["input"][-1]["output"] = scenario.output.replace("<elapsed>", wrong)
        with pytest.raises(ValueError):
            scenario(request, 2)
