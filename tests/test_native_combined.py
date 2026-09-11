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
    assert_native_identity,
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
    ("native_combined_mcp_tools.json",
     "19d0ce92c181de4ef0a5256c3a256695c4207f2346f28a3bdba69002f2c800c5"),
    ("native_combined_context.json",
     "be9e009b12e23ecf51472047ae79868fd98ff518cc8505a2fe94e7d52eb67299"),
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


def test_refusal_message_cannot_hide_a_patch_side_effect():
    from tests.substrate.test_native_combined import assert_patch_effect

    assert_patch_effect({"patch_directory": {"entries": []}}, False)
    with pytest.raises(AssertionError):
        assert_patch_effect({"patch_directory": {"entries": [{"fileName": "inert"}]}}, False)


def test_mcp_positive_control_never_broadens_the_empty_recipe():
    from dataclasses import replace

    scenario = CombinedScenario(MODELS[0], ("2026-09-11",), "exec_command",
                                {"cmd": "true"}, "unsupported call: exec_command")
    request = request_for(scenario, 1)
    request["tools"] = tools_for(mcp=True)
    replace(scenario, mcp=True)(request, 1)
    with pytest.raises(ValueError, match="instructions or tools"):
        scenario(request, 1)


def test_plugin_positive_context_never_becomes_ambient(scenario):
    from dataclasses import replace

    selected = replace(scenario, plugins=True)
    request = request_for(selected, 1)
    selected(request, 1)
    with pytest.raises(ValueError, match="context or conversation"):
        scenario(request, 1)


def test_original_sol_agent_context_is_absent_from_the_restricted_recipe():
    scenario = CombinedScenario(MODELS[1], ("2026-09-11",), "exec", {}, None)
    request = request_for(scenario, 1)
    assert len(request["input"]) == 5
    extra = json.loads(Path(__file__).with_name("fixtures").joinpath(
        "native_combined_context.json",
    ).read_text())["sol_multi_agent"]
    request["input"][3:3] = [{"id": f"agent-{index}", **item} for index, item in enumerate(extra)]
    with pytest.raises(ValueError, match="context or conversation"):
        scenario(request, 1)


def test_failed_untrusted_hook_attempt_is_not_a_disable_proof():
    from tests.substrate.test_combined_startup_origins import assert_hook_attempt

    record = {"wire": [], "marker": {"dataBase64": "YWJzZW50"}}
    assert_hook_attempt(record, False)
    record["wire"] = [{"received": {"method": method, "params": {"run": {
        "status": "failed", "entries": [{"kind": "error", "text":
                                          "No such file or directory (os error 2)"}],
    }}}} for method in ("hook/started", "hook/completed")]
    assert_hook_attempt(record, True)
    with pytest.raises(AssertionError):
        assert_hook_attempt(record, False)


def completed_hook_record():
    hook = {"eventName": "sessionStart", "sourcePath": "/tmp/home/.codex/hooks.json"}
    return {
        "protocol": {"thread": "fixture-thread", "turn": "fixture-turn"},
        "hooks": {"data": [{"hooks": [hook]}]},
        "marker": {"dataBase64": "aG9vaw=="},
        "wire": [{"received": {"method": method, "params": {
            "threadId": "fixture-thread", "turnId": "fixture-turn",
            "run": {**hook, "id": "fixture-hook", "entries": [], "status": status},
        }}} for method, status in (("hook/started", "running"), ("hook/completed", "completed"))],
    }


@pytest.mark.parametrize("damage", [
    "status", "entries", "thread", "turn", "pair", "source", "event", "start-status",
    "missing-start", "duplicate", "missing-marker", "negative-attempt", "negative-marker",
])
def test_successful_hook_proof_requires_execution_and_correlated_events(damage):
    from tests.substrate.test_combined_startup_origins import assert_hook_attempt

    record = completed_hook_record()
    assert_hook_attempt(record, True, completed=True)
    end = record["wire"][-1]["received"]["params"]
    enabled = not damage.startswith("negative-")
    if damage == "status":
        end["run"]["status"] = "failed"
    elif damage == "entries":
        end["run"]["entries"] = [{"kind": "error", "text": "inert failure"}]
    elif damage in {"thread", "turn"}:
        end[damage + "Id"] = "foreign"
    elif damage in {"pair", "source", "event"}:
        end["run"][{"pair": "id", "source": "sourcePath", "event": "eventName"}[damage]] = "foreign"
    elif damage == "start-status":
        record["wire"][0]["received"]["params"]["run"]["status"] = "completed"
    elif damage == "missing-start":
        del record["wire"][0]
    elif damage == "duplicate":
        record["wire"] += deepcopy(record["wire"])
    elif damage in {"missing-marker", "negative-attempt"}:
        record["marker"]["dataBase64"] = "YWJzZW50"
    elif damage == "negative-marker":
        record["wire"] = []
    with pytest.raises(AssertionError):
        assert_hook_attempt(record, enabled, completed=True)


def test_shell_selection_is_an_exact_context_variant(scenario):
    from dataclasses import replace

    from tests.native_combined import controlled_configuration

    selected = replace(scenario, packaged_shell=True)
    request = request_for(selected, 1)
    # Pin independently; generating both sides from prefix() alone is no proof.
    context = request["input"][-2]["content"][0]["text"]
    assert "<shell>zsh</shell>" in context
    assert "<shell>sh</shell>" in request_for(scenario, 1)["input"][-2]["content"][0]["text"]
    selected(request, 1)
    with pytest.raises(ValueError, match="context or conversation"):
        scenario(request, 1)
    for model in MODELS:
        base = controlled_configuration(model)
        assert "shell_zsh_fork = false" in base
        assert controlled_configuration(model, packaged_shell=True) == base.replace(
            "shell_zsh_fork = false", "shell_zsh_fork = true",
        )


@pytest.mark.parametrize("phase", ["untrusted", "trusted", "disabled"])
async def test_native_hook_matrix_cannot_skip_a_phase(monkeypatch, phase):
    from tests.substrate import test_combined_startup_origins as native

    calls = []

    async def measure(*_args, **kwargs):
        ordinal = len(calls)
        calls.append(kwargs)
        assert kwargs["packaged_shell"] is True
        enabled = ordinal != 2
        trusted = ordinal != 0
        record = completed_hook_record()
        record["hooks"]["data"][0]["hooks"][0].update(
            trustStatus="trusted" if trusted else "untrusted", enabled=enabled,
            key="fixture-key", currentHash="fixture-hash",
        )
        if not (enabled and trusted):
            record["wire"] = []
            record["marker"]["dataBase64"] = "YWJzZW50"
        if ("untrusted", "trusted", "disabled")[ordinal] == phase:
            # A failed attempt is not non-execution; a missing marker is not
            # positive execution even when native events claim completion.
            if ordinal == 1:
                record["marker"]["dataBase64"] = "YWJzZW50"
            else:
                record["wire"] = completed_hook_record()["wire"]
        return record

    monkeypatch.setattr(native, "measure", measure)
    with pytest.raises(AssertionError):
        await native.test_packaged_shell_executes_only_the_exact_trusted_hook(
            None, None, MODELS[0], "json",
        )
    assert len(calls) == ("untrusted", "trusted", "disabled").index(phase) + 1


@pytest.mark.parametrize("origin", ["json", "toml"])
async def test_native_origin_test_inspects_the_untrusted_attempt(monkeypatch, origin):
    from tests.substrate import test_combined_startup_origins as native

    calls = 0

    async def measure(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        attempted = calls != 3
        return {
            "hooks": {"data": [{"hooks": [{
                "trustStatus": "untrusted" if calls == 1 else "trusted",
                "enabled": attempted, "key": "fixture", "currentHash": "fixture-hash",
            }]}]},
            "marker": {"dataBase64": "YWJzZW50"},
            "wire": [{"received": {"method": method, "params": {"run": {
                "status": "failed", "entries": [{"kind": "error", "text":
                                                  "No such file or directory (os error 2)"}],
            }}}} for method in ("hook/started", "hook/completed")] if attempted else [],
        }

    monkeypatch.setattr(native, "measure", measure)
    with pytest.raises(AssertionError):
        await native.test_user_hook_discovery_trust_and_disable_have_execution_controls(
            None, None, origin,
        )


@pytest.mark.parametrize("operation,namespace", [("exec", "functions"),
                                               ("spawn_agent", "collaboration")])
def test_refused_call_namespace_is_part_of_the_observation(scenario, operation, namespace):
    from dataclasses import replace

    scenario = replace(scenario, tool=operation, namespace=namespace,
                       arguments={"code": "inert"} if operation == "exec" else {})
    request = request_for(scenario, 2)
    scenario(request, 2)
    request["input"][-2]["namespace"] = "foreign"
    with pytest.raises(ValueError, match="context or conversation"):
        scenario(request, 2)


@pytest.mark.parametrize("field", ["thread", "turn"])
def test_peer_metadata_must_correlate_with_the_same_native_rpc(field):
    protocol = {"thread": "thread-fixture", "turn": "turn-fixture"}
    request = {"client_metadata": {"thread_id": "thread-fixture", "turn_id": "turn-fixture"}}
    assert_native_identity(protocol, [request, deepcopy(request)])
    request["client_metadata"][field + "_id"] = "foreign"
    with pytest.raises(AssertionError):
        assert_native_identity(protocol, [request])


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
