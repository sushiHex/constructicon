"""Combined native observations inside the approved test-only placement."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from constructicon.core.executor import TaskSpec
from tests.containedworld import RecordedExecutorProvider
from tests.native_codex_probe import PROBE_PROMPT, conversation
from tests.native_combined import BASE_INSTRUCTIONS, CombinedScenario, controlled_configuration
from tests.native_startup import MODELS
from tests.substrate.test_contained_workspace import context
from tests.substrate.test_contained_workspace import provider as provider
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import PROGRAM, WORKER
from tests.substrate.test_native_startup import assert_outcome
from tests.substrate.test_provider_placement import observe, placement
from tests.substrate.test_provider_placement import placement_image as placement_image


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("operation", ["contained_python", "apply_patch", "view_image"])
async def test_combined_native_dispatch_and_refusal(
    placement_image, launcher, tmp_path, provider, model, operation,
):
    provider.launcher = launcher
    executor = RecordedExecutorProvider(launcher, provider, WORKER)
    await executor.qualify()
    workspace = await provider.acquire(context())
    acquired = await executor.acquire(context(binding="executor"))
    observed = []
    arguments = {
        "contained_python": {"program": PROGRAM},
        "apply_patch": {"patch": "*** Begin Patch\n*** Add File: /tmp/native-startup/inert\n"
                                 "+fixture only\n*** End Patch\n"},
        "view_image": {"path": "/tmp/native-startup/inert.png"},
    }[operation]
    kind = "custom tool call" if operation == "apply_patch" else "call"
    output = (json.dumps({"contained": True}) if operation == "contained_python" else
              f"unsupported {kind}: {operation}")
    now = datetime.now(UTC)
    # The shared deadline is 20 seconds. Name the UTC date variation explicitly;
    # it is not read from the native request that this assertion will inspect.
    dates = tuple(dict.fromkeys([
        now.date().isoformat(), (now + timedelta(seconds=20)).date().isoformat(),
    ]))
    scenario = CombinedScenario(model, dates, operation, arguments, output)

    async def worker(program):
        assert operation == "contained_python" and program == PROGRAM
        result = await acquired.resource.execute(
            TaskSpec(instruction=program), workspace=workspace.resource,
            grants=acquired.resource.context.binding.effective_grants,
        )
        observed.append({"status": result.status, "output": result.output})
        assert result.status == "success" and result.output == {"contained": True}
        return json.dumps(result.output)

    async def query(wire, record):
        record["placement"] = (await wire.read())["placement"]
        record["bootstrap"] = await wire.read()
        record["protocol"] = await conversation(
            wire, "/tmp/native-startup", worker, model=model, base_instructions=BASE_INSTRUCTIONS,
        )
        record["config"] = await wire.rpc("config/read", {"includeLayers": True})
        record["workers"] = observed
        await wire.io.close_stdin()

    try:
        await workspace.materialize()
        await acquired.materialize()
        async with placement(
            placement_image, model=model, scenario=PROBE_PROMPT, tool=operation,
            arguments=arguments, request_check=scenario,
        ) as (composed, peer, record):
            record["combined"] = {"model": model, "operation": operation, "dates": dates}
            observations, result = await observe(
                composed, peer, tmp_path, query=query, record=record,
                config=controlled_configuration(model),
            )
        assert_outcome(result)
        assert len(peer.requests) == 2 and not peer.failures
        for ordinal, request in enumerate(peer.requests, 1):
            scenario(request, ordinal)
        assert all(observations["bootstrap"]["absent"].values())
        assert observations["protocol"]["calls"] == (
            ["call_probe"] if operation == "contained_python" else []
        )
        assert observed == ([{"status": "success", "output": {"contained": True}}]
                            if operation == "contained_python" else [])
    finally:
        await executor.close(acquired, "discard")
        await provider.close(workspace, "discard")
    assert acquired.resource.active is None
    assert provider.closure.is_closed(acquired.resource.paths)
    assert not workspace.resource.paths.payload.exists()
