"""Combined native observations inside the approved test-only placement."""

import base64
import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from constructicon.core.executor import TaskSpec
from constructicon.substrate.executors.linux import LinuxLauncher
from tests.containedworld import RecordedExecutorProvider
from tests.native_codex_probe import CANARY_PNG, CATALOG_SHA256, PROBE_PROMPT, conversation
from tests.native_combined import BASE_INSTRUCTIONS, CombinedScenario, controlled_configuration
from tests.native_startup import MODELS
from tests.substrate.test_contained_workspace import context
from tests.substrate.test_contained_workspace import provider as provider
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import PROGRAM, WORKER
from tests.substrate.test_native_startup import assert_outcome
from tests.substrate.test_provider_placement import observe, placement
from tests.substrate.test_provider_placement import placement_image as placement_image


async def worker_result(resource, workspace, program, observations):
    result = await resource.execute(
        TaskSpec(instruction=program), workspace=workspace,
        grants=resource.context.binding.effective_grants,
    )
    observations.append(result.model_dump(mode="json"))
    assert result.status == "success" and result.output == {"contained": True}
    return json.dumps(result.output)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("operation,positive", [
    ("contained_python", False), ("apply_patch", False), ("view_image", False),
    ("apply_patch", True), ("view_image", True),
])
async def test_combined_native_dispatch_and_refusal(
    placement_image, launcher, tmp_path, provider, model, operation, positive, monkeypatch,
):
    provider.launcher = launcher
    executor = RecordedExecutorProvider(launcher, provider, WORKER)
    await executor.qualify()
    workspace = await provider.acquire(context())
    acquired = await executor.acquire(context(binding="executor"))
    observed = []
    processes = []
    original_run = LinuxLauncher.run

    async def record_process(self, command, **kwargs):
        result = await original_run(self, command, **kwargs)
        if command == ("/usr/bin/python3", "-I", "-c", WORKER):
            processes.append({**asdict(result), "stdout": result.stdout.hex(),
                              "stderr": result.stderr.hex()})
        return result

    monkeypatch.setattr(LinuxLauncher, "run", record_process)
    arguments = {
        "contained_python": {"program": PROGRAM},
        "apply_patch": {"patch": "*** Begin Patch\n*** Add File: /tmp/native-startup/inert\n"
                                 "+fixture only\n*** End Patch\n"},
        "view_image": {"path": "/tmp/native-startup/inert.png"},
    }[operation]
    kind = "custom tool call" if operation == "apply_patch" else "call"
    output = (json.dumps({"contained": True}) if operation == "contained_python" else
              f"unsupported {kind}: {operation}")
    config = controlled_configuration(model, images=positive and operation == "view_image")
    files = {}
    if positive and operation == "view_image":
        output = [{"type": "input_image", "detail": "high", "image_url":
                   "data:image/png;base64," + base64.b64encode(CANARY_PNG).decode()}]
    if positive and operation == "apply_patch":
        source = Path(os.environ["M8_CODEX_CATALOG"]).read_bytes()
        assert hashlib.sha256(source).hexdigest() == CATALOG_SHA256
        files["/tmp/home/.codex/control-catalog.json"] = source.decode()
        config = config.replace('model_catalog_json = "/opt/native-startup/catalog.json"',
                                'model_catalog_json = "/tmp/home/.codex/control-catalog.json"')
        output = ("Exit code: 0\nWall time: <elapsed> seconds\nOutput:\n"
                  "Success. Updated the following files:\nA /tmp/native-startup/inert\n")
    now = datetime.now(UTC)
    # The shared deadline is 20 seconds. Name the UTC date variation explicitly;
    # it is not read from the native request that this assertion will inspect.
    dates = tuple(dict.fromkeys([
        now.date().isoformat(), (now + timedelta(seconds=20)).date().isoformat(),
    ]))
    scenario = CombinedScenario(model, dates, operation, arguments, output,
                                images=positive and operation == "view_image",
                                restricted=not (positive and operation == "apply_patch"))

    async def worker(program):
        assert operation == "contained_python" and program == PROGRAM
        return await worker_result(acquired.resource, workspace.resource, program, observed)

    async def query(wire, record):
        record["workers"] = observed
        record["worker_processes"] = processes
        record["worker_acquisition"] = {
            "lease_id": str(acquired.lease_id), "resource_ref": acquired.resource_ref,
            "acquisition_id": acquired.acquisition_id,
            "run_lease": acquired.resource.context.run_lease.model_dump(mode="json"),
            "binding": acquired.resource.context.binding.model_dump(mode="json"),
            "path": acquired.resource.context.path.model_dump(mode="json"),
        }
        record["placement"] = (await wire.read())["placement"]
        record["bootstrap"] = await wire.read()

        async def canary(wire):
            # Trusted controller RPC, never a model operation. The marker is
            # inert public fixture data in the native private filesystem.
            if operation == "view_image":
                record["canary_setup"] = await wire.rpc("fs/writeFile", {
                    "path": arguments["path"], "dataBase64": base64.b64encode(CANARY_PNG).decode(),
                })

        record["protocol"] = await conversation(
            wire, "/tmp/native-startup", worker, model=model, base_instructions=BASE_INSTRUCTIONS,
            before_thread=canary,
        )
        if positive and operation == "apply_patch":
            record["patch_file"] = await wire.rpc("fs/readFile", {
                "path": "/tmp/native-startup/inert",
            })
        record["config"] = await wire.rpc("config/read", {"includeLayers": True})
        await wire.io.close_stdin()

    try:
        await workspace.materialize()
        await acquired.materialize()
        async with placement(
            placement_image, model=model, scenario=PROBE_PROMPT, tool=operation,
            arguments=arguments, request_check=scenario,
        ) as (composed, peer, record):
            record["combined"] = {"model": model, "operation": operation, "dates": dates,
                                  "positive": positive}
            observations, result = await observe(
                composed, peer, tmp_path, query=query, record=record,
                config=config, files=files,
            )
        assert_outcome(result)
        assert len(peer.requests) == 2 and not peer.failures
        for ordinal, request in enumerate(peer.requests, 1):
            scenario(request, ordinal)
        if positive and operation == "apply_patch":
            assert base64.b64decode(observations["patch_file"]["dataBase64"], validate=True) == (
                b"fixture only\n"
            )
        assert all(observations["bootstrap"]["absent"].values())
        assert observations["protocol"]["calls"] == (
            ["call_probe"] if operation == "contained_python" else []
        )
        assert [(item["status"], item["output"]) for item in observed] == (
            [("success", {"contained": True})] if operation == "contained_python" else []
        )
        assert len(processes) == (1 if operation == "contained_python" else 0)
        for process in processes:
            assert process["returncode"] == process["payload_returncode"] == 0
            assert process["timed_out"] is False and process["bound_exceeded"] is None
    finally:
        await executor.close(acquired, "discard")
        await provider.close(workspace, "discard")
    assert acquired.resource.active is None
    assert provider.closure.is_closed(acquired.resource.paths)
    assert not workspace.resource.paths.payload.exists()
