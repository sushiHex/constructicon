"""Opt-in native evidence. No account or remote provider can be reached.

The CI process lives in a fresh, loopback-only network namespace, with its own
PID namespace and an empty environment. The fake Responses endpoint speaks the
documented custom-provider protocol; it does not emulate authentication.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from constructicon.core.executor import TaskSpec
from constructicon.core.identity import parse_json_value
from tests.containedworld import RecordedExecutorProvider
from tests.native_codex_probe import CANARY_PNG, RECORD_BYTES, run_probe
from tests.substrate.test_contained_workspace import context
from tests.substrate.test_contained_workspace import provider as provider
from tests.substrate.test_linux_containment import launcher as launcher

WORKER = "import sys; exec(sys.stdin.read())"
PROGRAM = (
    "import json, pathlib\n"
    "assert not pathlib.Path('/etc/shadow').exists()\n"
    "try:\n"
    "    pathlib.Path('/workspace/forbidden-write').write_text('must refuse')\n"
    "except OSError as exc:\n"
    "    assert exc.errno == 30\n"
    "else:\n"
    "    raise AssertionError('READ mount was writable')\n"
    "print(json.dumps({'type':'result','output':{'contained':True}}))\n"
)


def events(items):
    response = {"id": "resp_probe", "object": "response", "model": "probe-model",
                "status": "in_progress", "output": []}
    yield {"type": "response.created", "response": response}
    for index, item in enumerate(items):
        yield {"type": "response.output_item.added", "output_index": index, "item": item}
        if item["type"] == "message":
            yield {"type": "response.output_text.delta", "output_index": index,
                   "content_index": 0, "item_id": item["id"], "delta": "fixture complete"}
        yield {"type": "response.output_item.done", "output_index": index, "item": item}
    yield {"type": "response.completed", "response": {
        **response, "status": "completed", "output": items,
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }}


@asynccontextmanager
async def fake_provider(tool, arguments):
    requests, failures = [], []
    handlers = set()

    async def respond(reader, writer):
        task = asyncio.current_task()
        handlers.add(task)
        try:
            async with asyncio.timeout(10):
                headers = await reader.readuntil(b"\r\n\r\n")
                lines = headers.decode("ascii").split("\r\n")
                assert lines[0] == "POST /v1/responses HTTP/1.1", lines[0]
                fields = dict(line.lower().split(":", 1) for line in lines[1:] if line)
                assert "authorization" not in fields  # No placeholder or token needed.
                size = int(fields["content-length"])
                assert 0 < size <= 1024 * 1024
                request = parse_json_value((await reader.readexactly(size)).decode())
                requests.append(request)
                assert len(requests) <= 2, "unexpected retry or extra turn"
                if len(requests) == 1:
                    items = [{"id": "fc_probe", "type": "function_call", "call_id": "call_probe",
                              "name": tool, "arguments": json.dumps(arguments)}]
                else:
                    items = [{"id": "msg_probe", "type": "message", "role": "assistant",
                              "status": "completed", "content": [
                                  {"type": "output_text", "text": "fixture complete"}]}]
                payload = b"".join(
                    ("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode()
                    for event in events(items)
                )
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n"
                    + f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload,
                )
                await writer.drain()
        except Exception as exc:
            failures.append(repr(exc))
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            finally:
                handlers.discard(task)

    server = await asyncio.start_server(respond, "127.0.0.1", 0, limit=RECORD_BYTES)
    try:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1", requests, failures
    finally:
        server.close()
        await server.wait_closed()
        pending = tuple(handlers)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.fixture
def native(tmp_path):
    binary = os.environ.get("M8_CODEX_BINARY")
    if sys.platform != "linux" or not binary:
        if os.environ.get("M8_NATIVE_CODEX_REQUIRED"):
            pytest.fail("required credential-free native CLI environment missing")
        pytest.skip("pinned Linux CLI probe not exercised; dedicated lane required")
    # An env flag is insufficient. Prove this namespace has no external interface
    # or route before executing the native harness (which is not yet trusted).
    interfaces = {line.split(":")[0].strip() for line in Path("/proc/net/dev").read_text()
                  .splitlines()[2:]}
    assert interfaces == {"lo"}, interfaces
    assert len(Path("/proc/net/route").read_text().splitlines()) == 1
    assert os.getuid() != 0
    assert not {key for key in os.environ if "TOKEN" in key or "API_KEY" in key}
    home = tmp_path / "empty-home"
    home.mkdir()
    env = {"HOME": str(home), "CODEX_HOME": str(home / ".codex"),
           "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    version = subprocess.check_output([binary, "--version"], env=env, cwd=tmp_path, timeout=15)
    assert version.strip() == b"codex-cli 0.153.4"
    return Path(binary), env


def write_evidence(name, value):
    directory = os.environ.get("M8_EVIDENCE_DIRECTORY")
    if directory:
        (Path(directory) / name).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def argv_for(native, cwd, endpoint, *, images):
    binary, env = native
    configuration = f'''
model = "probe-model"
model_provider = "probe"
model_context_window = 32768
model_auto_compact_token_limit = 30000
check_for_update_on_startup = false
web_search = "disabled"
[model_providers.probe]
name = "Credential-free loopback fixture"
base_url = "{endpoint}"
wire_api = "responses"
requires_openai_auth = false
request_max_retries = 0
stream_max_retries = 0
stream_idle_timeout_ms = 10000
[features]
view_image = {str(images).lower()}
shell_tool = false
unified_exec = false
apply_patch_freeform = false
multi_agent = false
code_mode = false
js_repl = false
apps = false
'''
    config = Path(env["CODEX_HOME"])
    config.mkdir()
    (config / "config.toml").write_text(configuration)
    return [str(binary), "app-server", "--strict-config", "--stdio"]


def test_pinned_native_schema_inventory(native, tmp_path):
    binary, env = native
    output = tmp_path / "schema"
    subprocess.run([str(binary), "app-server", "generate-json-schema", "--experimental",
                    "--out", str(output)], check=True, env=env, cwd=tmp_path, timeout=30,
                   capture_output=True)
    schemas = {path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
               for path in output.rglob("*.json")}
    params = json.loads((output / "DynamicToolCallParams.json").read_text())
    assert set(params["required"]) == {"arguments", "callId", "threadId", "tool", "turnId"}
    client = json.loads((output / "ClientRequest.json").read_text())
    methods = sorted({variant["properties"]["method"]["enum"][0]
                      for variant in client["oneOf"]})
    features = subprocess.check_output(
        [str(binary), "features", "list"], env=env, cwd=tmp_path, timeout=15,
    ).decode()
    flags = {line.split()[0]: line.split()[-1] for line in features.splitlines()}
    assert flags["view_image"] == "true"
    write_evidence("codex-schema.json", {"schemas": schemas, "client_methods": methods,
                                        "default_features": features,
                                        "binary_sha256": hashlib.sha256(binary.read_bytes())
                                        .hexdigest()})
    assert "thread/start" in methods and "turn/start" in methods


@pytest.mark.parametrize("operation", ["contained_python", "exec_command", "view_image"])
@pytest.mark.parametrize("images", [True, False], ids=["image-control", "image-disabled"])
async def test_native_dynamic_dispatch_and_builtin_probe(
    native, tmp_path, provider, launcher, operation, images,
):
    provider.launcher = launcher
    executor = RecordedExecutorProvider(launcher, provider, WORKER)
    await executor.qualify()
    workspace = await provider.acquire(context())
    acquired = await executor.acquire(context(binding="executor"))
    await workspace.materialize()
    await acquired.materialize()
    observed = []

    async def worker(program):
        result = await acquired.resource.execute(
            TaskSpec(instruction=program), workspace=workspace.resource,
            grants=acquired.resource.context.binding.effective_grants,
        )
        assert result.status == "success", result
        observed.append(result.output)
        return json.dumps(result.output)

    # A canary in the harness home is NOT a credential. A disabled built-in
    # reaching it would refute exclusive mediation despite a successful callback.
    canary = Path(native[1]["HOME"]) / "builtin-bypass"
    image_canary = Path(native[1]["HOME"]) / "private.png"
    image_canary.write_bytes(CANARY_PNG)
    arguments = {
        "contained_python": {"program": PROGRAM +
                             f"assert not pathlib.Path({str(image_canary)!r}).exists()\n"},
        "exec_command": {"cmd": f"printf bypass > {canary}", "max_output_tokens": 100},
        "view_image": {"path": str(image_canary)},
    }[operation]
    try:
        async with fake_provider(operation, arguments) as (endpoint, requests, failures):
            argv = argv_for(native, tmp_path, endpoint, images=images)
            result = await run_probe(argv, cwd=tmp_path, env=native[1], worker=worker)
            evidence = {"probe": operation, "images_enabled": images,
                        "protocol": result, "requests": requests,
                        "server_failures": failures, "worker_outputs": observed,
                        "builtin_canary_written": canary.exists()}
            write_evidence(f"codex-{operation}-images-{str(images).lower()}.json", evidence)
            assert not failures, failures
            assert len(requests) == 2
            expected_tools = {"request_user_input", "contained_python"}
            if images:
                expected_tools.add("view_image")
            assert {tool["name"] for tool in requests[0]["tools"]} == expected_tools
            outputs = [item for item in requests[1]["input"]
                       if item.get("type") == "function_call_output"]
            assert len(outputs) == 1
            if operation == "contained_python":
                assert result["calls"] == ["call_probe"]
                assert observed == [{"contained": True}]
            else:
                assert not observed
                assert not result["calls"]
                if operation == "exec_command" or not images:
                    assert outputs[0]["output"] == f"unsupported call: {operation}"
                    assert not canary.exists()
                else:
                    # A PASS reproduces the negative result: this native reader
                    # bypasses the worker and exports an unmounted harness file.
                    image = outputs[0]["output"][0]
                    assert image["type"] == "input_image"
                    assert image["image_url"].startswith("data:image/png;base64,")
                    assert base64.b64decode(image["image_url"].split(",", 1)[1],
                                            validate=True) == CANARY_PNG
    finally:
        await executor.close(acquired, "discard")
        await provider.close(workspace, "discard")
    assert acquired.resource.active is None
    assert provider.closure.is_closed(acquired.resource.paths)
    assert not workspace.resource.paths.payload.exists()
